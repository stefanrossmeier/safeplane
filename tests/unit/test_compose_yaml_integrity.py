from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


ROOT = Path(__file__).resolve().parents[2]


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@pytest.mark.parametrize(
    "compose_path",
    sorted(ROOT.glob("docker-compose*.yml")),
    ids=lambda path: path.name,
)
def test_compose_yaml_rejects_duplicate_mapping_keys(compose_path: Path) -> None:
    yaml.load(compose_path.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)
