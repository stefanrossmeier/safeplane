.PHONY: setup test validate validate-v1 validate-v2 run run-v1 run-v2 docker-run corpus-check corpus-check-v1 corpus-check-v2

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

test:
	.venv/bin/pytest

validate: validate-v2

validate-v1:
	.venv/bin/safeplane-routing-advisor validate --repo-root ../.. --version v1

validate-v2:
	.venv/bin/safeplane-routing-advisor validate --repo-root ../.. --version v2

run: run-v2

run-v1:
	.venv/bin/safeplane-routing-advisor run --repo-root ../.. --version v1 --output-dir reports/v1

run-v2:
	.venv/bin/safeplane-routing-advisor run --repo-root ../.. --version v2 --output-dir reports/v2

docker-run:
	docker compose run --rm routing-advisor

corpus-check: corpus-check-v1 corpus-check-v2

corpus-check-v1:
	.venv/bin/python scripts/build_corpus.py --check data/corpus.v1.json

corpus-check-v2:
	.venv/bin/python scripts/build_corpus_v2.py --check data/corpus.v2.json
