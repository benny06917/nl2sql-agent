
from typing import Optional, TypedDict

class AgentState(TypedDict, total=False):
    question: str                 
    schema: str                  

    sql: str                      
    attempts: int               
    error: Optional[str]        

    columns: list[str]            
    rows: list[tuple]             

    answer: str                 
    critic_ok: bool              
    critic_feedback: Optional[str]  
    history: list[dict]        
