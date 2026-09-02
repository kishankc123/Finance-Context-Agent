"""Orchestrate the four-step analysis workflow for portfolio and filing review.

This module validates input state, runs the portfolio context planner, filing
retrieval, disclosure change detection, and analyst memo steps in sequence, and
provides both a LangGraph-compiled graph and a direct async fallback runner.
"""

from __future__ import annotations

from fincontext_schemas import AnalysisState

from app.agents.analyst_memo import analyst_memo
from app.agents.disclosure_change import disclosure_change
from app.agents.filing_retrieval import filing_retrieval
from app.agents.portfolio_context_planner import portfolio_context_planner


def ensure_state(state: AnalysisState | dict) -> AnalysisState:
    if isinstance(state, AnalysisState):
        return state
    return AnalysisState.model_validate(state)


async def run_analysis_graph(state: AnalysisState) -> AnalysisState:
    """Run the workflow directly; useful for tests and as a fallback."""
    state = await portfolio_context_planner(state)
    state = await filing_retrieval(state)
    state = await disclosure_change(state)
    state = await analyst_memo(state)
    return state


def build_graph() -> object:
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return None

    graph = StateGraph(AnalysisState)

    '''Create async functions for each node in the graph that will call the corresponding agent 
    function with the validated state'''

    
    async def planner_node(state: AnalysisState | dict) -> AnalysisState:
        return await portfolio_context_planner(ensure_state(state))

    async def retrieval_node(state: AnalysisState | dict) -> AnalysisState:
        return await filing_retrieval(ensure_state(state))

    async def change_node(state: AnalysisState | dict) -> AnalysisState:
        return await disclosure_change(ensure_state(state))

    async def memo_node(state: AnalysisState | dict) -> AnalysisState:
        return await analyst_memo(ensure_state(state))

    #Create the graph nodes by taking each part of LangGraph as a node in the graph
    graph.add_node("portfolio_context_planner", planner_node)
    graph.add_node("filing_retrieval", retrieval_node)
    graph.add_node("disclosure_change", change_node)
    graph.add_node("analyst_memo", memo_node)

    #Set the entry point of the graph to the first node, which is the portfolio context planner
    graph.set_entry_point("portfolio_context_planner")

    #creating the edges of the graph to connect each node in sequence, creating a directed graph 
    # that represents the workflow
    graph.add_edge("portfolio_context_planner", "filing_retrieval")
    graph.add_edge("filing_retrieval", "disclosure_change")
    graph.add_edge("disclosure_change", "analyst_memo")
    graph.add_edge("analyst_memo", END)
    return graph.compile()


COMPILED_GRAPH = build_graph()


async def analyze(state: AnalysisState) -> AnalysisState:
    if COMPILED_GRAPH is None:
        return await run_analysis_graph(state)
    result = await COMPILED_GRAPH.ainvoke(state)
    if isinstance(result, AnalysisState):
        return result
    return AnalysisState.model_validate(result)
