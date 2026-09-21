from safeplane_routing_advisor.jev import JevClient


def test_parse_openrouter_decisions_response() -> None:
    assessment = JevClient._parse(
        {
            "id": "gen-dec-test",
            "model": "typesafe/jev-1.13-20260917",
            "provider": "TypeSafe",
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "developer",
                    "confidence": 0.98,
                    "probabilities": {
                        "chat": 0.01,
                        "assistant": 0.01,
                        "developer": 0.97,
                        "unclear": 0.01,
                    },
                },
                "ambiguous": {"type": "noul", "noul": 0.02},
                "repository_work": {"type": "noul", "noul": 0.99},
                "missing_repository_profile": {"type": "noul", "noul": 0.96},
                "assistant_tool_need": {"type": "noul", "noul": 0.01},
            },
            "usage": {"input_tokens": 500, "output_tokens": 100, "cost": 0.000021},
        }
    )
    assert assessment.route == "developer"
    assert assessment.route_margin == 0.96
    assert assessment.missing_repository_profile_probability == 0.96
    assert assessment.usage.estimated_cost_usd == 0.000021
