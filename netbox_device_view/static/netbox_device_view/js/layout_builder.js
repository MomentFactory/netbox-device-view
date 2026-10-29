(function () {
    var EMPTY = ".";
    var BASE_SELECTOR = ".deviceview.area";
    // Keep in sync with grid_css.py.
    var FILLER_PATTERN = /^(\.+|x|y|z|s\d+|__space__)$/;
    var AREA_PATTERN = /^-?[a-zA-Z_][a-zA-Z0-9_-]*$/;
    var SELECTOR_PATTERN = /^\.deviceview(\.[A-Za-z_][\w-]*)*$/;

    function safeParse(value, fallback) {
        try {
            return JSON.parse(value || "");
        } catch (error) {
            return fallback;
        }
    }

    function isEmptyToken(token) {
        return !token || FILLER_PATTERN.test(token);
    }

    function normalizeToken(token) {
        token = String(token || "").trim();
        return isEmptyToken(token) ? EMPTY : token;
    }

    function squash(text) {
        return String(text || "").split(/\s+/).filter(Boolean).join(" ");
    }

    function looseKey(name) {
        return String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    }

    function makeLayout(selector, label, grid, declarations) {
        var rows = (grid || []).map(function (row) { return (row || []).map(normalizeToken); });
        var columns = rows.reduce(function (largest, row) { return Math.max(largest, row.length); }, 0);
        rows = rows.map(function (row) {
            while (row.length < columns) row.push(EMPTY);
            return row;
        });
        return {
            selector: squash(selector) || BASE_SELECTOR,
            label: squash(label),
            rows: rows.length,
            columns: columns,
            grid: rows,
            declarations: String(declarations || "").trim(),
        };
    }

    function emptyGrid(rows, columns) {
        var grid = [];
        for (var r = 0; r < rows; r += 1) {
            grid.push([]);
            for (var c = 0; c < columns; c += 1) grid[r].push(EMPTY);
        }
        return grid;
    }

    // Mirrors grid_css.generate_layout_css so the Advanced CSS matches what the server saves.
    function layoutCss(layout) {
        var lines = [];
        if (layout.label) lines.push("/* " + squash(layout.label.replace(/\*\//g, "* /")) + " */");
        lines.push(layout.selector + " {");
        layout.declarations.split(/\r?\n/).forEach(function (declaration) {
            declaration = declaration.trim().replace(/;+$/, "").trim();
            if (declaration) lines.push("    " + declaration + ";");
        });
        lines.push("    grid-template-areas:");
        lines.push(layout.grid.map(function (row) { return '        "' + row.join(" ") + '"'; }).join("\n") + ";");
        lines.push("}");
        return lines.join("\n");
    }

    function areaProblems(grid) {
        var problems = {};
        var cells = {};
        grid.forEach(function (row, r) {
            row.forEach(function (token, c) {
                if (token === EMPTY) return;
                if (!AREA_PATTERN.test(token)) {
                    problems[token] = "is not a valid area name";
                    return;
                }
                (cells[token] = cells[token] || []).push([r, c]);
            });
        });
        Object.keys(cells).forEach(function (token) {
            var positions = cells[token];
            var rows = positions.map(function (p) { return p[0]; });
            var cols = positions.map(function (p) { return p[1]; });
            var area = (Math.max.apply(null, rows) - Math.min.apply(null, rows) + 1) * (Math.max.apply(null, cols) - Math.min.apply(null, cols) + 1);
            if (positions.length !== area) problems[token] = "must fill a rectangle";
        });
        return problems;
    }

    function variantName(layout) {
        if (layout.label) return layout.label;
        var selector = layout.selector;
        if (selector === BASE_SELECTOR) return "Base";
        if (/\.dFront\b/.test(selector)) return "Front";
        if (/\.dRear\b/.test(selector)) return "Rear";
        var module = selector.match(/\.module([\w-]+)/);
        if (module) return "Module " + module[1];
        return selector;
    }

    function initBuilder(root) {
        if (root.getAttribute("data-initialized")) return;
        root.setAttribute("data-initialized", "true");

        var form = root.closest("form");
        var deviceTypes = safeParse((document.getElementById("device-layout-data") || {}).textContent, []);
        var deviceTypeOptions = safeParse((document.getElementById("device-layout-options") || {}).textContent, []);
        var initialLayout = safeParse((document.getElementById("device-layout-initial") || {}).textContent, {});
        var dataUrlTemplate = root.getAttribute("data-layout-data-url-template") || "";
        var defaultDeviceTypeId = root.getAttribute("data-default-device-type-id") || "";
        var previewUrl = root.getAttribute("data-preview-url") || "";
        var parseUrl = root.getAttribute("data-parse-url") || "";
        var devicesUrlTemplate = root.getAttribute("data-devices-url-template") || "";

        function $(selector) { return root.querySelector(selector); }
        var input = $("[data-layout-config-input]");
        var cssTextarea = form ? form.querySelector("textarea[name=grid_template_area]") : null;
        var deviceTypeSelect = $("[data-device-type-select]");
        var referenceDeviceSelect = $("[data-reference-device]");
        var rowsInput = $("[data-rows]");
        var columnsInput = $("[data-columns]");
        var gridEl = $("[data-grid]");
        var image = $("[data-front-image]");
        var imageEmpty = $("[data-front-image-empty]");
        var variantTabs = $("[data-variant-tabs]");
        var variantLabel = $("[data-variant-label]");
        var variantSelector = $("[data-variant-selector]");
        var variantDeclarations = $("[data-variant-declarations]");
        var removeVariantButton = $("[data-remove-variant]");
        var statusEl = $("[data-status]");
        var cellEditor = $("[data-cell-editor]");
        var cellTokenSelect = $("[data-cell-token-select]");
        var selectedCellLabel = $("[data-selected-cell-label]");
        var startColumnInput = $("[data-start-column]");
        var unplacedEl = $("[data-unplaced]");
        var unplacedTitle = $("[data-unplaced-title]");
        var unplacedList = $("[data-unplaced-list]");
        var matchLegacyButton = $("[data-match-legacy]");
        var overlayControls = $("[data-overlay-controls]");
        var overlayToggle = $("[data-overlay-toggle]");
        var overlayOpacity = $("[data-overlay-opacity]");
        var overlayImg = $("[data-overlay-img]");
        var previewOutput = $("[data-preview-output]");
        var previewSize = $("[data-preview-size]");
        var previewVariant = $("[data-preview-variant]");

        var config = safeParse(input.value, {});
        var layouts = [];
        var extraCss = "";
        var active = 0;
        var currentDeviceType = null;
        var selectedCell = null;
        var selectedPattern = "paired";
        var previewTimer = null;
        var previewRequest = 0;
        var parseError = "";

        function layout() { return layouts[active]; }

        function addDeviceTypeOption(deviceType) {
            if (deviceTypeSelect.querySelector('option[value="' + deviceType.id + '"]')) return;
            var option = document.createElement("option");
            option.value = deviceType.id;
            option.textContent = deviceType.model;
            deviceTypeSelect.appendChild(option);
        }

        deviceTypeOptions.forEach(addDeviceTypeOption);
        deviceTypes.forEach(addDeviceTypeOption);

        // ---- reference device type templates -------------------------------------------

        function templateChoices() {
            var values = [];
            if (!currentDeviceType) return values;
            [
                ["interfaces", "Interface"],
                ["front_ports", "Front port"],
                ["rear_ports", "Rear port"],
                ["console_ports", "Console"],
            ].forEach(function (group) {
                (currentDeviceType[group[0]] || []).forEach(function (item) {
                    values.push({ value: item.area, label: group[1] + ": " + item.name, name: item.name });
                });
            });
            return values;
        }

        function knownAreas() {
            var known = {};
            templateChoices().forEach(function (choice) { known[choice.value] = choice; });
            return known;
        }

        function labelForToken(value, known) {
            if (!value || value === EMPTY) return "";
            return known[value] ? known[value].name : value;
        }

        // ---- sync -----------------------------------------------------------------------

        function buildConfig() {
            return {
                version: 2,
                mode: "builder",
                source_device_type_id: currentDeviceType ? currentDeviceType.id : null,
                layouts: layouts,
                extra_css: extraCss,
            };
        }

        function generatedCss() {
            var blocks = layouts.map(layoutCss);
            if (extraCss.trim()) blocks.push(extraCss.trim());
            return blocks.join("\n\n");
        }

        function sync() {
            input.value = JSON.stringify(buildConfig());
            if (cssTextarea && !parseError) cssTextarea.value = generatedCss();
            schedulePreview();
        }

        function setStatus(message, kind) {
            statusEl.innerHTML = "";
            if (!message) return;
            var alert = document.createElement("div");
            alert.className = "alert alert-" + (kind || "warning") + " py-2 mb-0";
            alert.textContent = message;
            statusEl.appendChild(alert);
        }

        // ---- rendering ------------------------------------------------------------------

        function renderTabs() {
            variantTabs.innerHTML = "";
            layouts.forEach(function (item, index) {
                var li = document.createElement("li");
                li.className = "nav-item";
                var button = document.createElement("button");
                button.type = "button";
                button.className = "nav-link" + (index === active ? " active" : "");
                button.textContent = variantName(item);
                button.title = item.selector;
                button.addEventListener("click", function () {
                    active = index;
                    selectedCell = null;
                    render();
                });
                li.appendChild(button);
                variantTabs.appendChild(li);
            });
            variantLabel.value = layout().label;
            variantSelector.value = layout().selector;
            variantSelector.classList.toggle("is-invalid", !SELECTOR_PATTERN.test(layout().selector));
            variantDeclarations.value = layout().declarations;
            removeVariantButton.disabled = layouts.length < 2;
            rowsInput.value = layout().rows;
            columnsInput.value = layout().columns;
            previewVariant.textContent = layouts.length > 1 ? "· " + variantName(layout()) : "";
        }

        function renderGrid() {
            var current = layout();
            var known = knownAreas();
            var checkUnmatched = templateChoices().length > 0;
            var problems = areaProblems(current.grid);
            gridEl.innerHTML = "";
            gridEl.style.gridTemplateColumns = "repeat(" + current.columns + ", minmax(2.6rem, 1fr))";

            current.grid.forEach(function (row, rowIndex) {
                row.forEach(function (value, columnIndex) {
                    var cell = document.createElement("button");
                    cell.type = "button";
                    var state = " is-empty";
                    if (value !== EMPTY) {
                        state = " is-interface";
                        if (problems[value]) state = " is-invalid";
                        else if (checkUnmatched && !known[value]) state = " is-unmatched";
                    }
                    cell.className = "layout-builder-cell" + state;
                    if (selectedCell && selectedCell.row === rowIndex && selectedCell.column === columnIndex) {
                        cell.className += " is-selected";
                    }
                    cell.title = value === EMPTY ? "Empty" : value + (problems[value] ? " – " + problems[value] : "");
                    cell.setAttribute("aria-label", "Row " + (rowIndex + 1) + ", column " + (columnIndex + 1) + ": " + cell.title);
                    var position = document.createElement("span");
                    position.className = "layout-builder-cell-pos";
                    position.textContent = (rowIndex + 1) + ":" + (columnIndex + 1);
                    var label = document.createElement("span");
                    label.className = "layout-builder-cell-value";
                    label.textContent = labelForToken(value, known);
                    cell.appendChild(position);
                    cell.appendChild(label);
                    cell.addEventListener("click", function () {
                        selectedCell = { row: rowIndex, column: columnIndex };
                        startColumnInput.value = columnIndex + 1;
                        renderGrid();
                        renderCellEditor();
                    });
                    gridEl.appendChild(cell);
                });
            });

            var problemTokens = Object.keys(problems);
            if (parseError) {
                setStatus(parseError, "danger");
            } else if (problemTokens.length) {
                setStatus("The browser will ignore this grid until these are fixed: " + problemTokens.map(function (token) {
                    return "'" + token + "' " + problems[token];
                }).join("; ") + ".", "danger");
            } else {
                setStatus("");
            }
            renderUnplaced(known);
        }

        function renderUnplaced(known) {
            var choices = templateChoices();
            var placed = {};
            layout().grid.forEach(function (row) { row.forEach(function (token) { placed[token] = true; }); });
            var missing = choices.filter(function (choice) { return !placed[choice.value]; });
            var unmatched = Object.keys(placed).filter(function (token) { return token !== EMPTY && !known[token]; });

            matchLegacyButton.hidden = !(choices.length && unmatched.length && legacyMatches().length);
            unplacedEl.hidden = !choices.length || !missing.length;
            unplacedList.innerHTML = "";
            if (unplacedEl.hidden) return;
            unplacedTitle.textContent = missing.length + " port" + (missing.length === 1 ? "" : "s") + " not placed in this variant" + (selectedCell ? " (click one to put it in the selected cell)" : " (select a cell, then click one to place it)") + ":";
            missing.forEach(function (choice) {
                var chip = document.createElement("button");
                chip.type = "button";
                chip.className = "btn btn-sm btn-outline-secondary";
                chip.textContent = choice.name;
                chip.addEventListener("click", function () {
                    if (!selectedCell) return;
                    layout().grid[selectedCell.row][selectedCell.column] = choice.value;
                    if (selectedCell.column + 1 < layout().columns) selectedCell.column += 1;
                    render();
                });
                unplacedList.appendChild(chip);
            });
        }

        function renderCellEditor() {
            if (!selectedCell) {
                cellEditor.hidden = true;
                return;
            }
            cellEditor.hidden = false;
            selectedCellLabel.textContent = "Selected cell R" + (selectedCell.row + 1) + " C" + (selectedCell.column + 1);
            var value = layout().grid[selectedCell.row][selectedCell.column];
            var choices = [{ value: EMPTY, label: "Empty" }].concat(templateChoices());
            if (!choices.some(function (choice) { return choice.value === value; })) {
                choices.push({ value: value, label: "Unmatched: " + value });
            }
            cellTokenSelect.innerHTML = "";
            if (cellTokenSelect.tomselect) {
                cellTokenSelect.tomselect.clear(true);
                cellTokenSelect.tomselect.clearOptions();
            }
            choices.forEach(function (choice) {
                var option = document.createElement("option");
                option.value = choice.value;
                option.textContent = choice.label;
                cellTokenSelect.appendChild(option);
                if (cellTokenSelect.tomselect) cellTokenSelect.tomselect.addOption({ value: choice.value, text: choice.label });
            });
            cellTokenSelect.value = value;
            if (cellTokenSelect.tomselect) {
                cellTokenSelect.tomselect.refreshOptions(false);
                cellTokenSelect.tomselect.setValue(value, true);
            }
        }

        function render() {
            if (selectedCell && (selectedCell.row >= layout().rows || selectedCell.column >= layout().columns)) selectedCell = null;
            renderTabs();
            renderGrid();
            renderCellEditor();
            sync();
        }

        // ---- grid editing ---------------------------------------------------------------

        function resize(rows, columns) {
            var current = layout();
            rows = Math.max(1, rows || 1);
            columns = Math.max(1, columns || 1);
            var next = emptyGrid(rows, columns);
            for (var r = 0; r < rows; r += 1) {
                for (var c = 0; c < columns; c += 1) {
                    if (current.grid[r] && current.grid[r][c]) next[r][c] = current.grid[r][c];
                }
            }
            current.grid = next;
            current.rows = rows;
            current.columns = columns;
        }

        function legacyMatches() {
            var byKey = {};
            templateChoices().forEach(function (choice) {
                var key = looseKey(choice.value);
                byKey[key] = byKey[key] === undefined ? choice.value : null; // ambiguous keys are skipped
            });
            var known = knownAreas();
            var matches = {};
            layouts.forEach(function (item) {
                item.grid.forEach(function (row) {
                    row.forEach(function (token) {
                        if (token === EMPTY || known[token]) return;
                        var target = byKey[looseKey(token)];
                        if (target) matches[token] = target;
                    });
                });
            });
            return Object.keys(matches).map(function (token) { return [token, matches[token]]; });
        }

        matchLegacyButton.addEventListener("click", function () {
            var matches = legacyMatches();
            if (!matches.length) return;
            var summary = matches.map(function (pair) { return pair[0] + " → " + pair[1]; }).join("\n");
            if (!window.confirm("Rename these grid names in every variant to match the reference device type?\n\n" + summary)) return;
            var map = {};
            matches.forEach(function (pair) { map[pair[0]] = pair[1]; });
            layouts.forEach(function (item) {
                item.grid = item.grid.map(function (row) {
                    return row.map(function (token) { return map[token] || token; });
                });
            });
            render();
        });

        $("[data-autofill]").addEventListener("click", function () {
            if (!currentDeviceType) return;
            var interfaces = (currentDeviceType.interfaces || []).slice();
            if ($("[data-reverse]").checked) interfaces.reverse();
            var startRow = selectedCell ? selectedCell.row : 0;
            var startColumn = selectedCell ? selectedCell.column : Math.max(1, parseInt(startColumnInput.value, 10) || 1) - 1;
            var selectedInterfaceIndex = interfaces.findIndex(function (iface) { return iface.area === cellTokenSelect.value; });
            if (selectedInterfaceIndex > 0) interfaces = interfaces.slice(selectedInterfaceIndex);
            var gapEvery = Math.max(0, parseInt($("[data-gap-every]").value, 10) || 0);
            var gapSize = Math.max(0, parseInt($("[data-gap-size]").value, 10) || 0);
            var grid = layout().grid;
            var rows = layout().rows;
            var columns = layout().columns;

            interfaces.forEach(function (iface, index) {
                var offset = index;
                if (gapEvery > 0 && gapSize > 0) offset += Math.floor(index / gapEvery) * gapSize;
                var row = startRow;
                var column = startColumn;

                if (selectedPattern === "linear") {
                    var linearOffset = (startRow * columns) + startColumn + offset;
                    row = Math.floor(linearOffset / columns);
                    column = linearOffset % columns;
                } else {
                    var pairedRows = Math.min(2, rows - startRow);
                    if (pairedRows < 2) {
                        column = startColumn + offset;
                    } else {
                        row = startRow + (offset % pairedRows);
                        column = startColumn + Math.floor(offset / pairedRows);
                    }
                }
                if (row < rows && column < columns) grid[row][column] = iface.area;
            });
            render();
        });

        $("[data-clear-grid]").addEventListener("click", function () {
            layout().grid = emptyGrid(layout().rows, layout().columns);
            selectedCell = null;
            render();
        });

        root.querySelectorAll("[data-pattern]").forEach(function (button) {
            button.addEventListener("click", function () {
                selectedPattern = button.getAttribute("data-pattern") || "paired";
                root.querySelectorAll("[data-pattern]").forEach(function (other) {
                    var isActive = other === button;
                    other.classList.toggle("active", isActive);
                    other.setAttribute("aria-pressed", isActive ? "true" : "false");
                });
            });
        });

        cellTokenSelect.addEventListener("change", function () {
            if (!selectedCell) return;
            layout().grid[selectedCell.row][selectedCell.column] = cellTokenSelect.value || EMPTY;
            render();
        });

        rowsInput.addEventListener("change", function () {
            resize(parseInt(rowsInput.value, 10), layout().columns);
            render();
        });
        columnsInput.addEventListener("change", function () {
            resize(layout().rows, parseInt(columnsInput.value, 10));
            render();
        });

        // ---- variants -------------------------------------------------------------------

        variantLabel.addEventListener("input", function () {
            layout().label = squash(variantLabel.value);
            renderTabs();
            sync();
        });
        variantSelector.addEventListener("change", function () {
            layout().selector = squash(variantSelector.value) || BASE_SELECTOR;
            renderTabs();
            sync();
        });
        variantDeclarations.addEventListener("change", function () {
            layout().declarations = variantDeclarations.value.trim();
            sync();
        });

        removeVariantButton.addEventListener("click", function () {
            if (layouts.length < 2) return;
            if (!window.confirm("Remove the \"" + variantName(layout()) + "\" variant?")) return;
            layouts.splice(active, 1);
            active = Math.max(0, active - 1);
            selectedCell = null;
            render();
        });

        root.querySelectorAll("[data-add-variant]").forEach(function (button) {
            button.addEventListener("click", function () {
                var kind = button.getAttribute("data-add-variant");
                var selector = BASE_SELECTOR;
                var label = "";
                if (kind === "module") {
                    var model = window.prompt("Module type model (as in NetBox, e.g. C9300-NM-8X):");
                    if (!model) return;
                    model = model.trim().replace(/\s+/g, "-");
                    selector = ".deviceview.module" + model + ".area";
                    label = (currentDeviceType ? currentDeviceType.model + " with " : "With ") + model;
                } else if (kind === "front") {
                    selector = ".deviceview.area.dFront";
                } else if (kind === "rear") {
                    selector = ".deviceview.area.dRear";
                } else {
                    selector = window.prompt("CSS selector:", ".deviceview.area");
                    if (!selector) return;
                }
                // Start from a copy of the current variant: module variants usually extend the base layout.
                var copy = makeLayout(selector, label, layout().grid.map(function (row) { return row.slice(); }), layout().declarations);
                layouts.push(copy);
                active = layouts.length - 1;
                selectedCell = null;
                render();
            });
        });

        // ---- Advanced CSS → builder ------------------------------------------------------

        function loadParsed(parsed) {
            layouts = (parsed.layouts || []).map(function (item) {
                return makeLayout(item.selector, item.label, item.grid, item.declarations);
            });
            extraCss = parsed.extra_css || "";
            if (active >= layouts.length) active = 0;
        }

        if (cssTextarea && parseUrl) {
            cssTextarea.addEventListener("change", function () {
                var body = new URLSearchParams();
                body.set("css", cssTextarea.value);
                fetch(parseUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
                    body: body.toString(),
                })
                    .then(function (response) {
                        return response.json().then(function (data) {
                            if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
                            return data;
                        });
                    })
                    .then(function (parsed) {
                        parseError = "";
                        loadParsed(parsed);
                        selectedCell = null;
                        // Re-render without rewriting the textarea the user just typed in.
                        renderTabs();
                        renderGrid();
                        renderCellEditor();
                        input.value = JSON.stringify(buildConfig());
                        schedulePreview();
                    })
                    .catch(function (error) {
                        parseError = "Could not load the Advanced CSS into the builder: " + error.message + " The builder is unchanged; the CSS will be saved as typed.";
                        renderGrid();
                    });
            });
        }

        // ---- preview --------------------------------------------------------------------

        function csrfToken() {
            var field = form && form.querySelector("[name=csrfmiddlewaretoken]");
            if (field) return field.value;
            var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
            return match ? decodeURIComponent(match[1]) : "";
        }

        function schedulePreview() {
            if (!previewUrl || !previewOutput) return;
            clearTimeout(previewTimer);
            previewTimer = setTimeout(refreshPreview, 400);
        }

        function refreshPreview() {
            var hasPorts = layout().grid.some(function (row) { return row.some(function (token) { return token !== EMPTY; }); });
            if (!hasPorts) {
                previewOutput.innerHTML = '<span class="text-muted">Assign ports in the grid to see a preview.</span>';
                return;
            }
            var body = new URLSearchParams();
            body.set("layout_config", input.value);
            body.set("variant", active);
            body.set("device_type_id", currentDeviceType ? currentDeviceType.id : "");
            body.set("device_id", referenceDeviceSelect.value || "");
            body.set("display_size", previewSize.value);
            var requestId = ++previewRequest;
            fetch(previewUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
                body: body.toString(),
            })
                .then(function (response) {
                    if (!response.ok) throw new Error("HTTP " + response.status);
                    return response.text();
                })
                .then(function (html) {
                    if (requestId !== previewRequest) return;
                    previewOutput.innerHTML = html;
                    if (window.bootstrap && window.bootstrap.Tooltip) {
                        previewOutput.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
                            new window.bootstrap.Tooltip(el);
                        });
                    }
                })
                .catch(function (error) {
                    if (requestId !== previewRequest) return;
                    previewOutput.innerHTML = '<div class="alert alert-danger mb-0"></div>';
                    previewOutput.firstChild.textContent = "Preview failed: " + error.message;
                });
        }

        referenceDeviceSelect.addEventListener("change", schedulePreview);
        previewSize.addEventListener("change", schedulePreview);

        // ---- reference device type and image --------------------------------------------

        function loadReferenceDevices(deviceTypeId) {
            referenceDeviceSelect.innerHTML = '<option value="">None - use device type templates</option>';
            if (!deviceTypeId || !devicesUrlTemplate || !window.fetch) return;
            var url = devicesUrlTemplate.replace("__device_type_id__", encodeURIComponent(deviceTypeId));
            fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
                .then(function (response) { return response.ok ? response.json() : { devices: [] }; })
                .then(function (data) {
                    (data.devices || []).forEach(function (device) {
                        var option = document.createElement("option");
                        option.value = device.id;
                        option.textContent = device.name;
                        referenceDeviceSelect.appendChild(option);
                    });
                })
                .catch(function () {});
        }

        function syncOverlay() {
            var hasImage = !image.hidden && image.getAttribute("src");
            overlayControls.hidden = !hasImage;
            var isActive = hasImage && overlayToggle.checked;
            overlayOpacity.disabled = !isActive;
            if (isActive) overlayImg.src = image.getAttribute("src");
            overlayImg.hidden = !isActive;
            overlayImg.style.opacity = (parseInt(overlayOpacity.value, 10) || 45) / 100;
        }

        overlayToggle.addEventListener("change", syncOverlay);
        overlayOpacity.addEventListener("input", syncOverlay);

        function applyDeviceType(deviceType) {
            currentDeviceType = deviceType;
            if (currentDeviceType) {
                var existingIndex = deviceTypes.findIndex(function (existing) { return existing.id === currentDeviceType.id; });
                if (existingIndex === -1) deviceTypes.push(currentDeviceType);
                else deviceTypes[existingIndex] = currentDeviceType;
                addDeviceTypeOption(currentDeviceType);
                deviceTypeSelect.value = currentDeviceType.id;

                // A brand-new, still empty layout takes its height from the device type.
                var untouched = layouts.length === 1 && !layout().grid.some(function (row) {
                    return row.some(function (token) { return token !== EMPTY; });
                });
                if (untouched) resize(currentDeviceType.rows || 2, layout().columns);

                if (currentDeviceType.front_image_url) {
                    image.src = currentDeviceType.front_image_url;
                    image.hidden = false;
                    imageEmpty.hidden = true;
                } else {
                    image.removeAttribute("src");
                    image.hidden = true;
                    imageEmpty.hidden = false;
                    imageEmpty.textContent = templateChoices().length
                        ? "No front-panel image is set for this reference device type."
                        : "This reference device type has no interface, port, or console templates to assign.";
                }
            } else {
                image.removeAttribute("src");
                image.hidden = true;
                imageEmpty.hidden = false;
                imageEmpty.textContent = "Select a reference device type to show its front-panel image.";
            }
            syncOverlay();
            loadReferenceDevices(currentDeviceType ? currentDeviceType.id : "");
            render();
        }

        function selectDeviceType(id) {
            var cached = deviceTypes.find(function (deviceType) { return String(deviceType.id) === String(id); });
            if (cached && (cached.interfaces || cached.front_ports || cached.rear_ports || cached.console_ports)) {
                applyDeviceType(cached);
                return;
            }
            if (!id) {
                applyDeviceType(null);
                return;
            }
            if (!dataUrlTemplate || !window.fetch) {
                applyDeviceType(null);
                imageEmpty.textContent = "Could not load interface templates: missing layout-data URL.";
                return;
            }
            image.hidden = true;
            imageEmpty.hidden = false;
            imageEmpty.textContent = "Loading reference device type...";
            var url = dataUrlTemplate.replace("__device_type_id__", encodeURIComponent(id));
            fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
                .then(function (response) {
                    if (!response.ok) throw new Error("HTTP " + response.status + " loading " + url);
                    return response.json();
                })
                .then(function (deviceType) { applyDeviceType(deviceType || null); })
                .catch(function (error) {
                    applyDeviceType(null);
                    imageEmpty.textContent = "Could not load interface templates: " + error.message;
                });
        }

        deviceTypeSelect.addEventListener("change", function () { selectDeviceType(deviceTypeSelect.value); });

        // ---- initial state --------------------------------------------------------------

        // The saved CSS (parsed server-side) is the source of truth; fall back to the
        // stored builder config, then to an empty base layout.
        if (initialLayout && (initialLayout.layouts || []).length) {
            loadParsed(initialLayout);
        } else if (config && config.mode === "builder" && (config.layouts || config.grid)) {
            loadParsed(config.layouts ? config : { layouts: [{ selector: BASE_SELECTOR, grid: config.grid }] });
        }
        if (!layouts.length) layouts = [makeLayout(BASE_SELECTOR, "", emptyGrid(2, 32), "")];

        var initialTypeId = (config && config.source_device_type_id) || defaultDeviceTypeId;
        if (initialTypeId) deviceTypeSelect.value = initialTypeId;
        render();
        selectDeviceType(deviceTypeSelect.value);
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-layout-builder]").forEach(initBuilder);
    });
}());
