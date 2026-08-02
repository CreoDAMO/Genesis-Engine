"""
Genesis Engine — Neo4j Knowledge Graph
Semantic triple store for strategies, markets, agents, and alpha correlations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase


class Neo4jKnowledgeGraph:
    """
    Knowledge graph schema:
      (Strategy)-[:GENERATES]->(Signal)
      (Market)-[:HAS_FEATURE]->(Feature)
      (Agent)-[:REPORTS]->(Alpha)
      (Alpha)-[:CORRELATES_WITH]->(Alpha)
      (Strategy)-[:PERFORMS_IN]->(Regime)
    """

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

    async def connect(self):
        self._driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))

    async def disconnect(self):
        if self._driver:
            await self._driver.close()

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    async def init_schema(self):
        async with self._driver.session() as session:
            await session.run("""
                CREATE CONSTRAINT strategy_id IF NOT EXISTS
                FOR (s:Strategy) REQUIRE s.id IS UNIQUE
            """)
            await session.run("""
                CREATE CONSTRAINT market_id IF NOT EXISTS
                FOR (m:Market) REQUIRE m.id IS UNIQUE
            """)
            await session.run("""
                CREATE CONSTRAINT agent_id IF NOT EXISTS
                FOR (a:Agent) REQUIRE a.id IS UNIQUE
            """)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def add_strategy(self, strategy_id: str, source_code: str, fitness: float, generation: int):
        async with self._driver.session() as session:
            await session.run("""
                MERGE (s:Strategy {id: $id})
                SET s.source = $source, s.fitness = $fitness, s.generation = $gen,
                    s.updated = datetime()
            """, id=strategy_id, source=source_code[:500], fitness=fitness, gen=generation)

    async def add_alpha_signal(self, agent_id: str, strategy_id: str, market_id: str,
                               direction: str, confidence: float, expected_return: float):
        async with self._driver.session() as session:
            await session.run("""
                MATCH (a:Agent {id: $agent_id}), (s:Strategy {id: $strategy_id}), (m:Market {id: $market_id})
                MERGE (alpha:Alpha {id: $alpha_id})
                SET alpha.direction = $direction, alpha.confidence = $confidence,
                    alpha.expected_return = $expected_return, alpha.timestamp = datetime()
                MERGE (a)-[:REPORTS]->(alpha)
                MERGE (s)-[:GENERATES]->(alpha)
                MERGE (alpha)-[:TARGETS]->(m)
            """, agent_id=agent_id, strategy_id=strategy_id, market_id=market_id,
                alpha_id=f"{agent_id}:{strategy_id}:{market_id}:{int(time.time())}",
                direction=direction, confidence=confidence, expected_return=expected_return)

    async def add_market(self, market_id: str, venue: str, asset: str, market_type: str = "prediction"):
        async with self._driver.session() as session:
            await session.run("""
                MERGE (m:Market {id: $id})
                SET m.venue = $venue, m.asset = $asset, m.type = $type,
                    m.updated = datetime()
            """, id=market_id, venue=venue, asset=asset, type=market_type)

    async def add_agent(self, agent_id: str, agent_type: str, wallet: Optional[str] = None):
        async with self._driver.session() as session:
            await session.run("""
                MERGE (a:Agent {id: $id})
                SET a.type = $type, a.wallet = $wallet, a.created = datetime()
            """, id=agent_id, type=agent_type, wallet=wallet or "")

    async def record_correlation(self, alpha_a: str, alpha_b: str, correlation: float):
        async with self._driver.session() as session:
            await session.run("""
                MATCH (a:Alpha {id: $a}), (b:Alpha {id: $b})
                MERGE (a)-[r:CORRELATES_WITH]->(b)
                SET r.correlation = $corr, r.updated = datetime()
            """, a=alpha_a, b=alpha_b, corr=correlation)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_top_strategies(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run("""
                MATCH (s:Strategy)
                RETURN s.id AS id, s.fitness AS fitness, s.generation AS generation
                ORDER BY s.fitness DESC LIMIT $limit
            """, limit=limit)
            return [record.data() async for record in result]

    async def get_agent_signals(self, agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run("""
                MATCH (a:Agent {id: $id})-[:REPORTS]->(alpha:Alpha)
                RETURN alpha.direction AS direction, alpha.confidence AS confidence,
                       alpha.expected_return AS expected_return, alpha.timestamp AS timestamp
                ORDER BY alpha.timestamp DESC LIMIT $limit
            """, id=agent_id, limit=limit)
            return [record.data() async for record in result]

    async def find_correlated_alphas(self, alpha_id: str, threshold: float = 0.7) -> List[Dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run("""
                MATCH (a:Alpha {id: $id})-[r:CORRELATES_WITH]-(b:Alpha)
                WHERE abs(r.correlation) >= $threshold
                RETURN b.id AS id, r.correlation AS correlation
            """, id=alpha_id, threshold=threshold)
            return [record.data() async for record in result]


import time
