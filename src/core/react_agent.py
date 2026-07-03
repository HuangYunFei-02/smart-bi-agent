"""
ReAct Agent - Reasoning + Acting Pattern
Core capabilities:
1. Autonomous decision: choose SQL query or Python calculation
2. Tool orchestration: SQL executor, Python calculator, data visualization
3. Explanatory answers: convert results to business language
"""
import json
import re
import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

class ToolType(Enum):
    SQL_QUERY = "sql_query"
    PYTHON_CALC = "python_calc"
    VISUALIZATION = "visualization"
    DIRECT_ANSWER = "direct_answer"

@dataclass
class AgentAction:
    tool: ToolType
    input_data: str
    reasoning: str = ""

@dataclass
class AgentObservation:
    status: str
    result: Any
    error_msg: str = ""

@dataclass
class AgentStep:
    thought: str
    action: AgentAction
    observation: AgentObservation

class ReActAgent:
    SYSTEM_PROMPT = """You are a Smart BI Agent that helps users analyze business data.
You have access to the following tools:

1. sql_query: Execute SQL queries against the database
   - Use for: data retrieval, aggregation, filtering, grouping
   - Input: SQL query string

2. python_calc: Execute Python code for calculations
   - Use for: complex math, statistical analysis, data transformation
   - Input: Python code string

3. visualization: Generate charts and graphs
   - Use for: creating visual representations of data
   - Input: JSON with chart_type, data, and options

4. direct_answer: Answer without tools
   - Use for: simple questions, explanations, clarifications
   - Input: answer text

Follow this format:
Thought: [your reasoning about what to do]
Action: [tool_name]
Action Input: [input for the tool]

After receiving observation:
Thought: [your reasoning about the result]
[Continue with next Action or Final Answer]

Final Answer: [your final response to the user]
"""

    def __init__(self, llm_client, schema_manager, fewshot_library, db_path: str):
        self.llm = llm_client
        self.schema = schema_manager
        self.fewshot = fewshot_library
        self.db_path = db_path
        self.max_steps = 5
        self.history: List[AgentStep] = []

    def run(self, user_query: str) -> Dict[str, Any]:
        """Execute full ReAct pipeline"""
        # Step 1: Intent recognition and schema mapping
        schema_text, relevant_tables = self.schema.get_relevant_schema(user_query)
        business_hint = self.schema.get_business_terms_hint(user_query)
        join_hint = self.schema.get_join_hints(relevant_tables)

        # Step 2: Retrieve few-shot examples
        similar_examples = self.fewshot.retrieve_similar(user_query, k=3)
        few_shot_prompt = self.fewshot.format_few_shot_prompt(similar_examples)

        # Step 3: Build prompt for SQL generation
        sql_prompt = self._build_sql_prompt(
            user_query, schema_text, business_hint, join_hint, few_shot_prompt
        )

        # Step 4: Generate SQL with LLM
        sql_response = self.llm.chat([
            {"role": "system", "content": "You are a SQL expert. Generate only executable SQLite SQL."},
            {"role": "user", "content": sql_prompt}
        ])

        sql = self._extract_sql(sql_response.content)

        # Step 5: Self-Correction
        sql = self._self_correct(sql, schema_text)

        # Step 6: Execute SQL
        data, columns, error = self._execute_sql(sql)

        if error:
            correction_prompt = self._build_correction_prompt(error, schema_text, user_query, sql)

            correction_response = self.llm.chat([
                {"role": "system", "content": "You are a SQL expert. Fix the SQL error."},
                {"role": "user", "content": correction_prompt}
            ])
            sql = self._extract_sql(correction_response.content)
            data, columns, error = self._execute_sql(sql)

        # Step 7: Determine if Python calculation is needed
        needs_calc = self._needs_calculation(user_query, data)

        calc_result = None
        if needs_calc and data:
            calc_result = self._execute_python_calc(user_query, data, columns)

        # Step 8: Generate visualization config
        viz_config = None
        if data and len(data) > 0:
            viz_config = self._generate_visualization_config(user_query, data, columns)

        # Step 9: Generate final explanation
        explanation = self._generate_explanation(
            user_query, sql, data, columns, calc_result, viz_config
        )

        return {
            "success": error is None,
            "final_answer": explanation,
            "sql": sql,
            "data": data,
            "columns": columns,
            "visualization": viz_config,
            "calculation": calc_result,
            "error": error,
            "steps": self._format_steps()
        }

    def _build_sql_prompt(self, query, schema, business_hint, join_hint, few_shot) -> str:
        parts = [
            "Generate a SQLite SQL query to answer the following question.",
            "",
            "=== DATABASE SCHEMA ===",
            schema,
            "",
            "=== BUSINESS HINTS ===",
            business_hint if business_hint else "None",
            "",
            "=== JOIN HINTS ===",
            join_hint if join_hint else "None",
            "",
            "=== EXAMPLES ===",
            few_shot if few_shot else "None",
            "",
            "=== TASK ===",
            "Question: " + query,
            "",
            "=== RULES ===",
            "1. Output ONLY the SQL query, no explanation, no markdown, no code blocks",
            "2. Use only tables and columns from the schema above",
            "3. Use proper JOIN conditions with ON clauses",
            "4. Filter orders with order_status = '已完成' (Chinese text) unless asked otherwise",
            "5. Calculate sales as: SUM(quantity * unit_price - discount_amount)",
            "6. The SQL must start with SELECT or WITH",
            "7. Do not use backticks, do not use markdown formatting",
            "8. End with a semicolon",
            "",
            "SQL:"
        ]
        return "\n".join(parts)

    def _build_correction_prompt(self, error, schema, user_query, sql) -> str:
        parts = [
            "Previous SQL failed with error: " + error,
            "Please fix the SQL query.",
            "",
            "Schema:",
            schema,
            "",
            "Original question: " + user_query,
            "Previous SQL: " + sql,
            "",
            "Generate corrected SQL:"
        ]
        return "\n".join(parts)

    def _extract_sql(self, text: str) -> str:
        # Remove markdown code blocks
        text = text.replace("```sql", "").replace("```", "").replace("`", "")

        # Find SQL starting with SELECT or WITH, stop at explanation text
        lines = text.strip().split("\n")
        sql_lines = []
        started = False

        for line in lines:
            line = line.strip()
            if not started:
                if line.upper().startswith(("SELECT", "WITH")):
                    started = True
                    sql_lines.append(line)
            else:
                # Stop if we hit explanation text
                if line.startswith("###") or line.startswith("**") or "Explanation" in line:
                    break
                sql_lines.append(line)

        if sql_lines:
            sql = " ".join(sql_lines)
            sql = sql.rstrip(";").strip()
            return sql

        # Fallback
        for line in lines:
            line = line.strip()
            if line.upper().startswith(("SELECT", "WITH")):
                clean = line.split("###")[0].split("**")[0].strip()
                return clean.rstrip(";").strip()

        return text.strip()

    def _self_correct(self, sql: str, schema: str) -> str:
        if not sql.upper().startswith(("SELECT", "WITH")):
            sql = "SELECT " + sql

        sql = re.sub(r"[`*#]", "", sql)
        return sql

    def _execute_sql(self, sql: str) -> Tuple[List[Dict], List[str], Optional[str]]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)

            columns = [description[0] for description in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            data = [dict(row) for row in rows]

            conn.close()
            return data, columns, None

        except Exception as e:
            return [], [], str(e)

    def _needs_calculation(self, query: str, data: List[Dict]) -> bool:
        calc_keywords = ["growth", "yoy", "mom", "rate", "trend", "correlation", "statistics", "distribution"]
        return any(kw in query.lower() for kw in calc_keywords) and len(data) > 1

    def _execute_python_calc(self, query: str, data: List[Dict], columns: List[str]) -> Dict:
        import statistics

        result = {
            "description": "Statistical analysis",
            "metrics": {}
        }

        for col in columns:
            values = [row.get(col) for row in data if row.get(col) is not None]
            if values and all(isinstance(v, (int, float)) for v in values):
                result["metrics"][col] = {
                    "count": len(values),
                    "sum": sum(values),
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values)
                }

        return result

    def _generate_visualization_config(self, query: str, data: List[Dict], columns: List[str]) -> Optional[Dict]:
        if not data or len(data) == 0:
            return None

        numeric_cols = []
        categorical_cols = []

        for col in columns:
            values = [row.get(col) for row in data[:5] if row.get(col) is not None]
            if values and all(isinstance(v, (int, float)) for v in values):
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)

        if len(data) > 10 and len(categorical_cols) > 0 and len(numeric_cols) > 0:
            chart_type = "line" if any(kw in query.lower() for kw in ["trend", "change", "time"]) else "bar"
            return {
                "chart_type": chart_type,
                "x_axis": categorical_cols[0],
                "y_axis": numeric_cols[0],
                "title": "Analysis: " + query[:30] + "..."
            }
        elif len(numeric_cols) >= 2:
            return {
                "chart_type": "scatter",
                "x_axis": numeric_cols[0],
                "y_axis": numeric_cols[1],
                "title": "Correlation: " + numeric_cols[0] + " vs " + numeric_cols[1]
            }
        elif len(data) <= 10 and len(categorical_cols) > 0 and len(numeric_cols) > 0:
            return {
                "chart_type": "pie",
                "category": categorical_cols[0],
                "value": numeric_cols[0],
                "title": "Distribution: " + categorical_cols[0]
            }

        return None

    def _generate_explanation(self, query: str, sql: str, data: List[Dict], 
                              columns: List[str], calc_result: Optional[Dict],
                              viz_config: Optional[Dict]) -> str:
        sample = json.dumps(data[:3] if data else "None", ensure_ascii=False, default=str)
        calc_json = json.dumps(calc_result, ensure_ascii=False, default=str) if calc_result else "None"

        context_parts = [
            "Question: " + query,
            "SQL: " + sql,
            "Results: " + str(len(data)) + " rows",
            "Columns: " + str(columns),
            "Sample data: " + sample
        ]

        if calc_result:
            context_parts.append("Calculations: " + calc_json)

        context = "\n".join(context_parts)

        prompt_parts = [
            "Based on the query results, provide a clear business explanation in Chinese.",
            "",
            context,
            "",
            "Requirements:",
            "1. Answer the original question directly",
            "2. Include key numbers and insights",
            "3. Keep it concise (under 200 words)",
            "4. Use business language, not technical terms",
            "",
            "Explanation:"
        ]
        prompt = "\n".join(prompt_parts)

        response = self.llm.chat([
            {"role": "system", "content": "You are a business analyst explaining data insights."},
            {"role": "user", "content": prompt}
        ])

        return response.content.strip()

    def _format_steps(self) -> List[Dict]:
        return [
            {
                "thought": step.thought,
                "action": step.action.tool.value,
                "status": step.observation.status,
                "result_preview": str(step.observation.result)[:200] if step.observation.result else ""
            }
            for step in self.history
        ]
