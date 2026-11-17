"""Unit tests for the slice modal's process-setting overrides."""

import json

from backend.app.services.process_overrides import (
    apply_process_overrides,
    normalise_process_overrides,
)


def _process(**values: str) -> str:
    return json.dumps({"inherits": "0.20mm Standard @BBL X1C", **values})


class TestNormaliseProcessOverrides:
    def test_bools_become_the_one_zero_strings_a_preset_stores(self):
        assert normalise_process_overrides({"enable_support": True}) == {"enable_support": "1"}
        assert normalise_process_overrides({"enable_support": False}) == {"enable_support": "0"}

    def test_numbers_become_strings(self):
        assert normalise_process_overrides({"wall_loops": 4, "layer_height": 0.16}) == {
            "wall_loops": "4",
            "layer_height": "0.16",
        }

    def test_strings_pass_through_including_the_percent_sign(self):
        # The frontend serialises percents with the sign; stripping it here
        # would silently change the value the slicer sees.
        assert normalise_process_overrides({"sparse_infill_density": "35%"}) == {"sparse_infill_density": "35%"}

    def test_vector_options_keep_their_list_shape(self):
        assert normalise_process_overrides({"default_acceleration": [500, 300]}) == {
            "default_acceleration": ["500", "300"]
        }

    def test_keys_that_are_not_config_identifiers_are_dropped(self):
        result = normalise_process_overrides({"wall_loops": 2, "Wall Loops": 3, "__proto__": 1, "a-b": 1, "": 1})
        assert result == {"wall_loops": "2"}

    def test_values_a_preset_cannot_hold_are_dropped_not_serialised(self):
        result = normalise_process_overrides({"wall_loops": 2, "nested": {"a": 1}, "none": None})
        assert result == {"wall_loops": "2"}

    def test_a_list_containing_a_non_scalar_drops_the_whole_key(self):
        # Half-applying a per-extruder vector would send a shorter list than the
        # printer has extruders, which is worse than not setting it at all.
        assert normalise_process_overrides({"default_acceleration": [500, {"a": 1}]}) == {}


class TestApplyProcessOverrides:
    def test_writes_the_users_values_into_the_process_json(self):
        result = apply_process_overrides(_process(), {"wall_loops": 4, "enable_support": True})
        assert json.loads(result)["wall_loops"] == "4"
        assert json.loads(result)["enable_support"] == "1"

    def test_keeps_the_inherits_stub_so_the_preset_still_resolves(self):
        # A "standard" preset pick is a {inherits: ...} stub; dropping that key
        # would leave the slicer with a handful of orphaned values.
        result = apply_process_overrides(_process(), {"wall_loops": 4})
        assert json.loads(result)["inherits"] == "0.20mm Standard @BBL X1C"

    def test_user_value_wins_over_one_already_in_the_preset(self):
        result = apply_process_overrides(_process(wall_loops="2"), {"wall_loops": 6})
        assert json.loads(result)["wall_loops"] == "6"

    def test_empty_overrides_leave_the_json_untouched(self):
        original = _process(wall_loops="2")
        assert apply_process_overrides(original, {}) == original

    def test_overrides_that_all_get_dropped_leave_the_json_untouched(self):
        original = _process(wall_loops="2")
        assert apply_process_overrides(original, {"Bad Key": 1}) == original

    def test_unparseable_process_json_degrades_to_a_plain_slice(self):
        # Better a slice with the picked preset than a failed one.
        assert apply_process_overrides("not json", {"wall_loops": 4}) == "not json"

    def test_non_object_process_json_degrades_to_a_plain_slice(self):
        assert apply_process_overrides("[1, 2]", {"wall_loops": 4}) == "[1, 2]"
