import re
import unittest
from pathlib import Path

from netbox_device_view.grid_css import (
    EMPTY_TOKEN,
    area_problems,
    describe_grid_css,
    generate_grid_css,
    normalize_config,
    parse_grid_css,
    validate_layout,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def example_css_files():
    files = {path.name: path.read_text() for path in sorted((REPO_ROOT / "examples").rglob("*.css"))}
    readme = (REPO_ROOT / "README.md").read_text()
    match = re.search(r"```\n(/\* C9300-24T \*/.*?)```", readme, re.S)
    if match:
        files["README"] = match.group(1)
    return files


def builder_config(parsed):
    return {"mode": "builder", "layouts": parsed["layouts"], "extra_css": parsed["extra_css"]}


class ExampleRoundTripTest(unittest.TestCase):
    def test_examples_found(self):
        self.assertGreater(len(example_css_files()), 10)

    def test_every_example_round_trips(self):
        for name, css in example_css_files().items():
            with self.subTest(example=name):
                parsed = parse_grid_css(css)
                self.assertTrue(parsed["layouts"], "no layout parsed")
                regenerated = generate_grid_css(builder_config(parsed))
                self.assertEqual(parse_grid_css(regenerated), parsed)

    def test_module_variant_is_kept(self):
        parsed = parse_grid_css((REPO_ROOT / "examples/Cisco/C9300-24T.css").read_text())
        selectors = [layout["selector"] for layout in parsed["layouts"]]
        self.assertEqual(selectors, [".deviceview.area", ".deviceview.moduleC9300-NM-8X.area"])
        self.assertEqual(parsed["layouts"][1]["label"], "C9300-24T with C9300-NM-8X")
        self.assertEqual(parsed["layouts"][1]["grid"][0][-1], "tengigabitethernet1-7")


class ParseTest(unittest.TestCase):
    def test_missing_semicolon_and_extra_declarations(self):
        css = """
        .deviceview.area.dFront {
            background: #000;
            grid-auto-rows: auto; grid-template-areas:
              "port-1 port-2 s0 port-3"
        }
        .deviceview.area.dRear { grid-template-areas: "port-1 port-2" }
        """
        parsed = parse_grid_css(css)
        front, rear = parsed["layouts"]
        self.assertEqual(front["selector"], ".deviceview.area.dFront")
        self.assertEqual(front["grid"], [["port-1", "port-2", EMPTY_TOKEN, "port-3"]])
        self.assertEqual(front["declarations"], "background: #000\ngrid-auto-rows: auto")
        self.assertEqual(rear["grid"], [["port-1", "port-2"]])

    def test_legacy_fillers_become_empty(self):
        parsed = parse_grid_css('.deviceview.area { grid-template-areas: "x y gi1 s0 s12 gi2 z"; }')
        self.assertEqual(parsed["layouts"][0]["grid"], [[".", ".", "gi1", ".", ".", "gi2", "."]])

    def test_spanning_port_is_kept(self):
        css = '.deviceview.area { grid-template-areas: "a hu25 hu25" "b hu25 hu25"; }'
        layout = parse_grid_css(css)["layouts"][0]
        self.assertEqual(layout["grid"], [["a", "hu25", "hu25"], ["b", "hu25", "hu25"]])
        self.assertEqual(validate_layout(layout), [])

    def test_ragged_rows_are_padded(self):
        layout = parse_grid_css('.deviceview.area { grid-template-areas: "a b c" "d"; }')["layouts"][0]
        self.assertEqual(layout["grid"], [["a", "b", "c"], ["d", ".", "."]])

    def test_unrelated_blocks_are_preserved(self):
        css = '.deviceview.area { grid-template-areas: "a"; }\n.foo, .bar { color: red; }\n@media print { .x { y: z; } }'
        parsed = parse_grid_css(css)
        self.assertEqual(len(parsed["layouts"]), 1)
        self.assertIn(".foo, .bar { color: red; }", parsed["extra_css"])
        self.assertIn("@media print", parsed["extra_css"])
        regenerated = generate_grid_css(builder_config(parsed))
        self.assertEqual(parse_grid_css(regenerated), parsed)

    def test_describe(self):
        self.assertEqual(describe_grid_css((REPO_ROOT / "examples/Cisco/C9300-24T.css").read_text()), "2 × 32 · 2 variants")
        self.assertEqual(describe_grid_css(""), "empty")
        self.assertEqual(describe_grid_css(".foo { color: red; }"), "custom CSS")


class GenerateTest(unittest.TestCase):
    def test_v1_config_is_upgraded(self):
        config = normalize_config({"mode": "builder", "rows": 1, "columns": 3, "grid": [["x", "gi1", "s0"]]})
        self.assertEqual(config["version"], 2)
        self.assertEqual(config["layouts"][0]["selector"], ".deviceview.area")
        self.assertEqual(config["layouts"][0]["grid"], [[".", "gi1", "."]])

    def test_empty_cells_are_dots(self):
        css = generate_grid_css({"mode": "builder", "grid": [["x", "gi1", "s0", "gi2", "z"]]})
        self.assertIn('". gi1 . gi2 ."', css)

    def test_non_builder_config_generates_nothing(self):
        self.assertEqual(generate_grid_css({}), "")
        self.assertEqual(generate_grid_css(None), "")

    def test_non_rectangular_area_is_rejected(self):
        problems = area_problems([["a", "b"], ["b", "a"]])
        self.assertEqual(set(problems), {"a", "b"})
        with self.assertRaises(ValueError):
            generate_grid_css({"mode": "builder", "grid": [["a", "b"], ["b", "a"]]})

    def test_bad_selector_and_declarations_are_rejected(self):
        for layout in (
            {"selector": "body", "grid": [["a"]]},
            {"selector": ".deviceview.area", "grid": [["a"]], "declarations": "color: red} body {color: blue"},
            {"selector": ".deviceview.area", "grid": [["a"]], "declarations": "x: </style><script>"},
        ):
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    generate_grid_css({"mode": "builder", "layouts": [layout]})

    def test_invalid_area_name_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_grid_css({"mode": "builder", "grid": [["1/0/1"]]})


if __name__ == "__main__":
    unittest.main()
