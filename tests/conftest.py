import os

# Settings the app needs, set before anything imports it.
os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("SESSION_BACKEND", "memory")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
# Turns on the supply-chain agent (its BigQuery calls are faked in the tests).
os.environ.setdefault("SUPPLY_CHAIN_GRAPH", "test-project.vehicle_supply_chain.SupplyChain")
