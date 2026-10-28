"""V2 schema and metrics using invented remarks and labels."""

from idx_agent.enrichment.v2 import (
    V2_FACETS,
    haiku_meets_dev_rule,
    message_parameters,
    parse_v2,
    score_v2,
    tool_schema,
)


def item(value, polarity="affirmed"):
    return {
        "kind": "facet",
        "group": "exterior_lot",
        "value": value,
        "polarity": polarity,
        "temporality": "current",
        "start": 0,
        "end": 6,
        "quote": "garage",
    }


def test_schema_is_only_twenty_categorical_facets():
    props = tool_schema()["input_schema"]["properties"]["annotations"]["items"][
        "properties"
    ]
    assert len(props["facet_value"]["enum"]) == 20
    assert set(props["facet_value"]["enum"]) == {
        v for group in V2_FACETS.values() for v in group
    }
    assert "number" not in props and "field" not in props


def test_request_uses_separate_remark_and_cached_fixed_prefix():
    request = message_parameters("invented-model", "fixed prompt", "invented remark")
    assert "invented remark" not in request["system"][0]["text"]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["tool_choice"] == {"type": "auto"}
    assert request["tools"][0] == tool_schema()


def test_model_decision_uses_three_percentage_points():
    assert haiku_meets_dev_rule(0.90, 0.87)
    assert haiku_meets_dev_rule(0.80, 0.90)
    assert not haiku_meets_dev_rule(0.90, 0.869)
    assert not haiku_meets_dev_rule(None, 0.9)


def test_v2_scoring_excludes_other_facets_and_numeric_but_keeps_polarity():
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [{"id": "1", "split": "dev", "text": "garage"}],
    }
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {
                "id": "1",
                "annotations": [
                    item("garage"),
                    item("corner_lot"),
                    {
                        "kind": "numeric",
                        "field": "bedrooms",
                        "value": 2,
                        "start": 0,
                        "end": 6,
                        "quote": "garage",
                    },
                ],
            }
        ],
    }
    pred = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": "1", "annotations": [item("garage", "negated")]}],
    }
    result = score_v2(sample, gold, pred, "dev")
    assert (
        result["overall"].expected,
        result["overall"].predicted,
        result["overall"].correct,
    ) == (1, 1, 0)


def test_parser_rejects_otherwise_valid_but_out_of_scope_facet():
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {
                    "annotations": [
                        {
                            "kind": "facet",
                            "group": "exterior_lot",
                            "facet_value": "corner_lot",
                            "polarity": "affirmed",
                            "temporality": "current",
                            "quote": "garage",
                        }
                    ]
                },
            }
        ]
    }
    result, errors = parse_v2(response, "garage")
    assert result == [] and errors[0]["rule"] == "v2_facet_required"


def test_dev_filter_never_reads_test_annotations():
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [
            {"id": "1", "split": "dev", "text": "garage"},
            {"id": "2", "split": "test", "text": ""},
        ],
    }
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {"id": "1", "annotations": [item("garage")]},
            {"id": "2", "annotations": None},
        ],
    }
    predictions = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {"id": "1", "annotations": [item("garage")]},
        ],
    }
    assert score_v2(sample, gold, predictions, "dev")["overall"].f1 == 1


def test_dev_comparison_runs_100_cases_per_explicit_model():
    from idx_agent.enrichment.v2 import compare_dev_cases

    cases = [(str(index), "garage") for index in range(100)]
    sent, saved = [], []
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ]
    }
    usage = {
        "input_tokens": 2,
        "output_tokens": 3,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1,
    }

    def invoke(model, text):
        sent.append((model, text))
        return response, usage, b"{}"

    predictions, reports = compare_dev_cases(
        "invented",
        cases,
        {"sonnet": "model-s", "haiku": "model-h"},
        invoke,
        lambda model, index, raw, use: saved.append((model, index)),
        lambda *_: None,
    )
    assert len(sent) == len(saved) == 200
    assert [row["id"] for row in predictions["sonnet"]["labels"]] == [
        key for key, _ in cases
    ]
    assert reports["haiku"]["usage"]["input_tokens"] == 200
    assert reports["sonnet"]["no_tool_calls"] == 0
