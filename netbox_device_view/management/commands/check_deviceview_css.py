from django.core.management.base import BaseCommand
from django.db import transaction

from netbox_device_view.grid_css import normalize_config, parse_grid_css, repair_css, validate_css
from netbox_device_view.models import DeviceView


class Command(BaseCommand):
    help = (
        "List DeviceViews whose stored CSS is invalid (unsafe text, broken quoting or braces, "
        "grids the browser rejects).  With --fix, repair what can be repaired automatically."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true", help="Save automatic repairs.")
        parser.add_argument("--show-css", action="store_true", help="Print the repaired CSS for each view.")

    def handle(self, *args, fix=False, show_css=False, **options):
        broken = fixed = remaining = 0
        for view in DeviceView.objects.prefetch_related("device_types").order_by("pk"):
            css = view.grid_template_area or ""
            problems = validate_css(css)
            if not problems:
                continue
            broken += 1
            types = ", ".join(dt.model for dt in view.device_types.all()) or "no device types"
            self.stdout.write(self.style.WARNING(f"#{view.pk} {view} ({types})"))
            for problem in problems:
                self.stdout.write(f"    - {problem}")

            repaired, left = repair_css(css)
            if repaired == css:
                self.stdout.write(self.style.ERROR("    no automatic repair; edit this view by hand"))
                remaining += 1
                continue
            label = "repaired" if not left else f"partly repaired, {len(left)} problem(s) left"
            self.stdout.write(self.style.SUCCESS(f"    {label}") if not left else f"    {label}:")
            for problem in left:
                self.stdout.write(f"      - {problem}")
            if show_css:
                self.stdout.write("    " + repaired.replace("\n", "\n    "))
            remaining += bool(left)
            if fix:
                with transaction.atomic():
                    view.snapshot()
                    view.grid_template_area = repaired
                    # Keep the visual builder in step with the CSS it will now open.
                    config = normalize_config(view.layout_config)
                    if config is not None:
                        parsed = parse_grid_css(repaired)
                        config.update(layouts=parsed["layouts"], extra_css=parsed["extra_css"])
                        view.layout_config = config
                    view.save()
                fixed += 1

        summary = f"{broken} invalid view(s); "
        summary += f"{fixed} saved" if fix else "run with --fix to save repairs"
        summary += f"; {remaining} still need a manual edit." if remaining else "."
        self.stdout.write(summary)
