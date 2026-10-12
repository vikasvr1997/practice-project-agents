class Agent:
    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role
        self.history: list[str] = []

    def remember(self, text:str) -> None:
        self.history.append(text)

    def describe(self) -> str: 
        return f"{self.name} ({self.role}) remembers {len(self.history)} things"

sql_bot = Agent("SQLBot", "writes BigQuery SQL")
support_bot = Agent("SupportBot", "answer customer Questions")

sql_bot.remember("user asked about Q3 sales")

print(sql_bot.describe())

print(support_bot.describe())


from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content:str
    created_at: datetime = field(default_factory= lambda: datetime.now(timezone.utc))

msg = Message("user", "What were total sales lasst month")
print(msg)



from abc import ABC, abstractmethod

class Tool(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def run(self, query: str) -> str: ...

class CalculatorTool(Tool):
    name = "calculator"
    desription = "Adds two numbers written like '2+3' "

    def run(self, query:str) -> str:
        a,b = query.split("+")
        return str(int(a) + int(b))
class FakeBigQueryTool(Tool):
    name = "calculator"
    description = "Answers questions about sales data"

    def __init__(self, table: str) -> None:
        self.table = table

    def run(self, query: str ) -> str:
        return f"SELECT SUM(amount) FROM '{self.table}'"

