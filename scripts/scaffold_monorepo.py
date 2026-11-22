import os

components = [
    ('contracts', 'Shared (Person A & Person B)', 'Pydantic models and JSON schemas for system-wide contracts.'),
    ('target-app', 'Person A', 'Target multi-service application (gateway, orders, payments + Postgres).'),
    ('infra', 'Person A', 'Docker Compose and Prometheus infrastructure definitions.'),
    ('faults', 'Person A', 'Fault injector framework and ground-truth YAML fault catalogue.'),
    ('detector', 'Person A', 'Signal detection, threshold monitoring, deduplication, and Incident creation.'),
    ('platform_api', 'Person A', 'FastAPI interface mediating all agent interactions with system telemetry and actions.'),
    ('deployer', 'Person A', 'Deployment and rollback execution engine emitting change events.'),
    ('verifier', 'Person A', 'Multi-stage fix verification: git worktree sandbox, canary testing, and metric recovery.'),
    ('bench', 'Person A', 'Benchmark harness, unattended evaluation runner, and metrics aggregator.'),
    ('agent', 'Person B', 'Investigator LLM agent, prompt loop, evidence citation, and hypothesis ranking.'),
    ('fixer', 'Person B', 'Fix generation engine producing minimal diffs, rollbacks, config updates, and regression tests.'),
    ('memory', 'Person B', 'Incident storage and semantic/category retrieval of past postmortems in SQLite.'),
    ('safety', 'Person B', 'Safety gate enforcing risk tiers (T0-T3), confidence thresholds, rate limits, and kill switch.'),
    ('reporter', 'Person B', 'Postmortem generator, Slack webhook reporter, and GitHub PR formatting.'),
    ('dashboard', 'Person B', 'Live real-time web dashboard displaying incident timeline, trace, and metric graphs.'),
    ('pitch', 'Person B', 'Business case, pitch deck materials, 3-minute demo script, and Q&A bank.'),
    ('orchestrator', 'Person B', 'Autonomous incident loop state machine wiring detection, RCA, fix, safety, and verification.')
]

base_dir = r'D:\Akshay\Documents\AI On-Call Engineer'

for name, owner, desc in components:
    dir_path = os.path.join(base_dir, name)
    os.makedirs(dir_path, exist_ok=True)
    
    # Python package file (skip target-app and infra for python module if needed, but safe to include)
    with open(os.path.join(dir_path, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write(f'"""{name} component package.\nOwner: {owner}\n"""\n')
    
    # Directory documentation
    with open(os.path.join(dir_path, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(f'# /{name}\n\n- **Owner:** {owner}\n- **Role:** {desc}\n\n*Refer to Architecture Section 5 for directory ownership and collaboration rules.*\n')

    # Component test directory
    test_dir = os.path.join(base_dir, 'tests', name)
    os.makedirs(test_dir, exist_ok=True)
    with open(os.path.join(test_dir, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write(f'"""Tests for {name}.\nOwner: {owner}\n"""\n')

print("All 17 component directories and corresponding test directories scaffolded.")
