import re
import unittest
from pathlib import Path

from netbox_device_view.grid_css import (
    EMPTY_TOKEN,
    area_problems,
    css_grid_problems,
    css_problems,
    css_syntax_problems,
    describe_grid_css,
    generate_grid_css,
    normalize_config,
    parse_grid_css,
    repair_css,
    validate_css,
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


class CssSafetyTest(unittest.TestCase):
    PAYLOADS = (
        ".deviceview.area { color: red; }</style><script>alert(1)</script>",
        ".deviceview.area { background: url(https://example.com/x.png); }",
        ".deviceview.area { background: URL ( //example.com ); }",
        "@import 'https://example.com/x.css';",
        ".deviceview.area { width: expression(alert(1)); }",
        ".deviceview.area { background: \\75 rl(//example.com); }",
    )

    def test_payloads_rejected(self):
        for css in self.PAYLOADS:
            with self.subTest(css=css):
                self.assertTrue(css_problems(css))

    def test_examples_accepted(self):
        for name, css in example_css_files().items():
            with self.subTest(example=name):
                self.assertEqual(css_problems(css), [])

    def test_extra_css_rejected(self):
        for css in self.PAYLOADS:
            with self.subTest(css=css):
                config = {"mode": "builder", "layouts": [_layout()], "extra_css": css}
                with self.assertRaises(ValueError):
                    generate_grid_css(config)

    def test_declarations_rejected(self):
        layout = _layout(declarations="background: url(//example.com/x.png)")
        self.assertTrue(validate_layout(layout))
        with self.assertRaises(ValueError):
            generate_grid_css({"mode": "builder", "layouts": [layout]})

    def test_label_cannot_close_style(self):
        layout = _layout(label="</style><script>alert(1)</script>")
        css = generate_grid_css({"mode": "builder", "layouts": [layout]})
        self.assertNotIn("<", css)
        self.assertEqual(css_problems(css), [])


# Stored on a real site after a spreadsheet round trip: the first row lost its
# opening quote and a stray quote follows the closing brace.  Printed into the
# shared <style>, the "}" ends up inside a string and every later rule (other
# devices' sizing) is swallowed.
IMPORT_DAMAGED = (
    '.deviceview.area { background-color: #d9d9d9; grid-template-areas: x x x x x x x x" '
    '"x x x gigabitethernet1 gigabitethernet2 s0 gigabitethernet3 s0 z "; }"'
)


class CssStructureTest(unittest.TestCase):
    def test_examples_are_valid(self):
        for name, css in example_css_files().items():
            with self.subTest(example=name):
                self.assertEqual(validate_css(css), [])

    def test_import_damage_is_blocking(self):
        problems = css_syntax_problems(IMPORT_DAMAGED)
        self.assertTrue(any("never closed" in problem for problem in problems))
        self.assertTrue(any("must be quoted" in problem for problem in problems))

    def test_syntax_problems(self):
        for css in (
            '.deviceview.area { grid-template-areas: "a b; }',
            ".deviceview.area { grid-template-areas: 'a b'; ",
            '.deviceview.area { grid-template-areas: "a b"; } }',
            '.deviceview.area { grid-template-areas: "a b"; } stray',
            '.deviceview.area { grid-template-areas: "a b"; } /* open',
        ):
            with self.subTest(css=css):
                self.assertTrue(css_syntax_problems(css))

    def test_valid_css_has_no_syntax_problems(self):
        css = '/* a } " */ .deviceview.area { grid-template-areas: "a b" \'c d\'; }\n.x[title="}"] { color: red; }'
        self.assertEqual(css_syntax_problems(css), [])

    def test_grid_problems(self):
        ragged = '.deviceview.area { grid-template-areas: "a b c" "d e"; }'
        self.assertIn("different numbers of cells (3, 2)", css_grid_problems(ragged)[0])
        # Legacy fillers are real area names to the browser, so they must be rectangles too.
        filler = '.deviceview.area { grid-template-areas: "x x a" "x b x"; }'
        self.assertTrue(any("'x'" in problem for problem in css_grid_problems(filler)))
        self.assertEqual(css_grid_problems('.deviceview.area { grid-template-areas: ". .. a" "b . ."; }'), [])

    def test_validate_reports_syntax_before_grid(self):
        self.assertEqual(validate_css(IMPORT_DAMAGED), css_syntax_problems(IMPORT_DAMAGED))

    def test_repair_import_damage(self):
        repaired, problems = repair_css(IMPORT_DAMAGED)
        self.assertEqual(problems, [])
        layout = parse_grid_css(repaired)["layouts"][0]
        self.assertEqual(layout["declarations"], "background-color: #d9d9d9")
        self.assertEqual(layout["grid"][1][3:6], ["gigabitethernet1", "gigabitethernet2", "."])

    def test_repair_leaves_real_conflicts(self):
        css = '.deviceview.area { grid-template-areas: "gi1 gi2" "gi2 gi1"; }'
        repaired, problems = repair_css(css)
        self.assertEqual(repaired, css)
        self.assertTrue(problems)

    def test_repair_keeps_valid_css(self):
        for name, css in example_css_files().items():
            with self.subTest(example=name):
                self.assertEqual(repair_css(css), (css, []))

    def test_builder_rejects_unbalanced_declarations(self):
        layout = _layout(declarations='font-family: "Mono')
        self.assertTrue(validate_layout(layout))


def _layout(**overrides):
    layout = {
        "selector": ".deviceview.area",
        "label": "",
        "grid": [["gi0-1", "gi0-2"]],
        "declarations": "",
    }
    layout.update(overrides)
    return layout


if __name__ == "__main__":
    unittest.main()
