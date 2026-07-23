(function () {
    var SPACE_TOKEN = "__space__";

    function slugArea(name, fallback) {
        var value = String(name || "").toLowerCase().replace(/[/.\s+]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
        if (!value && fallback) value = "iface-" + fallback;
        if (value && (/^[0-9-]/).test(value)) value = "p" + value;
        return value;
    }

    function safeParse(value, fallback) {
        try {
            return JSON.parse(value || "");
        } catch (error) {
            return fallback;
        }
    }

    function isSpacerToken(token) {
        return token === SPACE_TOKEN || /^s\d+$/.test(token);
    }

    function isEmptyToken(token) {
        return !token || token === "." || token === "x" || token === "z" || isSpacerToken(token);
    }

    function cssRowsFromGrid(grid) {
        var spacerNames = {};
        var spacerCount = 0;

        return grid.map(function (row) {
            var firstComponent = -1;
            var lastComponent = -1;

            row.forEach(function (token, columnIndex) {
                if (!isEmptyToken(token)) {
                    if (firstComponent === -1) firstComponent = columnIndex;
                    lastComponent = columnIndex;
                }
            });

            return row.map(function (token, columnIndex) {
                token = token || ".";
                if (token === "x" || token === "z") return token;
                if (token === ".") {
                    if (firstComponent === -1 || columnIndex < firstComponent) return "x";
                    if (columnIndex > lastComponent) return "z";
                }
                if (token === "." || isSpacerToken(token)) {
                    var spacerKey = columnIndex + ":" + (token === "." ? "auto" : "space");
                    if (!Object.prototype.hasOwnProperty.call(spacerNames, spacerKey)) {
                        spacerNames[spacerKey] = "s" + spacerCount;
                        spacerCount += 1;
                    }
                    return spacerNames[spacerKey];
                }
                return token;
            });
        });
    }

    function cssFromConfig(config) {
        if (!config || config.mode !== "builder") return "";
        var rows = cssRowsFromGrid(config.grid || []).map(function (row) {
            return '    "' + row.join(" ") + '"';
        });
        return ".deviceview.area {\n    grid-template-areas:\n" + rows.join("\n") + ";\n}";
    }

    function initBuilder(root) {
        var dataScript = document.getElementById("device-layout-data");
        var optionsScript = document.getElementById("device-layout-options");
        var deviceTypes = safeParse(dataScript ? dataScript.textContent : "[]", []);
        var deviceTypeOptions = safeParse(optionsScript ? optionsScript.textContent : "[]", []);
        var dataUrlTemplate = root.getAttribute("data-layout-data-url-template") || "";
        var defaultDeviceTypeId = root.getAttribute("data-default-device-type-id") || "";
        var input = root.querySelector("[data-layout-config-input]");
        var deviceTypeSelect = root.querySelector("[data-device-type-select]");
        var rowsInput = root.querySelector("[data-rows]");
        var columnsInput = root.querySelector("[data-columns]");
        var gridEl = root.querySelector("[data-grid]");
        var imageWrap = root.querySelector("[data-front-image-wrap]");
        var image = root.querySelector("[data-front-image]");
        var imageEmpty = root.querySelector("[data-front-image-empty]");
        var cssPreview = root.querySelector("[data-css-preview]");
        var cellEditor = root.querySelector("[data-cell-editor]");
        var cellTokenSelect = root.querySelector("[data-cell-token-select]");
        var selectedCellLabel = root.querySelector("[data-selected-cell-label]");
        var startColumnInput = root.querySelector("[data-start-column]");
        var config = safeParse(input.value, {});
        var grid = [];
        var currentDeviceType = null;
        var selectedCell = null;
        var selectedPattern = "paired";

        function addDeviceTypeOption(deviceType) {
            if (deviceTypeSelect.querySelector('option[value="' + deviceType.id + '"]')) return;
            var option = document.createElement("option");
            option.value = deviceType.id;
            option.textContent = deviceType.model;
            deviceTypeSelect.appendChild(option);
        }

        deviceTypeOptions.forEach(addDeviceTypeOption);
        deviceTypes.forEach(addDeviceTypeOption);

        function tokens() {
            var values = [
                { value: ".", label: "Empty (.)" },
                { value: SPACE_TOKEN, label: "Space" },
            ];
            if (!currentDeviceType) return values;

            function appendGroup(items, prefix) {
                items.forEach(function (item) {
                    values.push({ value: item.area || slugArea(item.name, item.id), label: prefix + ": " + item.name });
                });
            }

            appendGroup(currentDeviceType.interfaces || [], "Interface");
            appendGroup(currentDeviceType.front_ports || [], "Front port");
            appendGroup(currentDeviceType.rear_ports || [], "Rear port");
            appendGroup(currentDeviceType.console_ports || [], "Console");
            return values;
        }

        function componentTemplateCount(deviceType) {
            if (!deviceType) return 0;
            return (deviceType.interfaces || []).length
                + (deviceType.front_ports || []).length
                + (deviceType.rear_ports || []).length
                + (deviceType.console_ports || []).length;
        }

        function labelForToken(value) {
            if (!value || value === ".") return "Empty";
            if (isSpacerToken(value)) return "Space";
            var match = tokens().find(function (choice) { return choice.value === value; });
            if (!match) return value;
            return match.label.replace(/^Interface: /, "").replace(/^Front port: /, "FP ").replace(/^Rear port: /, "RP ").replace(/^Console: /, "CON ");
        }

        function tokenClass(value) {
            if (!value || value === ".") return " is-empty";
            if (value === "x" || value === "z" || isSpacerToken(value)) return " is-spacer";
            return " is-interface";
        }

        function resizeGrid(rows, columns) {
            var next = [];
            for (var r = 0; r < rows; r += 1) {
                next[r] = [];
                for (var c = 0; c < columns; c += 1) {
                    next[r][c] = grid[r] && grid[r][c] ? grid[r][c] : ".";
                }
            }
            grid = next;
        }

        function renderGrid() {
            var rows = parseInt(rowsInput.value, 10) || 2;
            var columns = parseInt(columnsInput.value, 10) || 32;
            resizeGrid(rows, columns);
            gridEl.innerHTML = "";
            gridEl.style.gridTemplateColumns = "repeat(" + columns + ", minmax(2.6rem, 1fr))";

            grid.forEach(function (row, rowIndex) {
                row.forEach(function (value, columnIndex) {
                    var cell = document.createElement("button");
                    cell.type = "button";
                    cell.className = "layout-builder-cell" + tokenClass(value);
                    if (selectedCell && selectedCell.row === rowIndex && selectedCell.column === columnIndex) {
                        cell.className += " is-selected";
                    }
                    cell.setAttribute("aria-label", "Row " + (rowIndex + 1) + ", column " + (columnIndex + 1));
                    var position = document.createElement("span");
                    position.className = "layout-builder-cell-pos";
                    position.textContent = (rowIndex + 1) + ":" + (columnIndex + 1);
                    var label = document.createElement("span");
                    label.className = "layout-builder-cell-value";
                    label.textContent = labelForToken(value);
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
            renderCellEditor();
            sync();
        }

        function renderCellEditor() {
            if (!selectedCell) {
                cellEditor.hidden = true;
                return;
            }
            cellEditor.hidden = false;
            selectedCellLabel.textContent = "Selected cell R" + (selectedCell.row + 1) + " C" + (selectedCell.column + 1);
            var value = grid[selectedCell.row] && grid[selectedCell.row][selectedCell.column] ? grid[selectedCell.row][selectedCell.column] : ".";
            var choices = tokens();
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
            if (!choices.some(function (choice) { return choice.value === value; })) {
                var custom = document.createElement("option");
                custom.value = value;
                custom.textContent = value;
                cellTokenSelect.appendChild(custom);
                if (cellTokenSelect.tomselect) cellTokenSelect.tomselect.addOption({ value: value, text: value });
            }
            cellTokenSelect.value = value;
            if (cellTokenSelect.tomselect) {
                cellTokenSelect.tomselect.refreshOptions(false);
                cellTokenSelect.tomselect.setValue(value, true);
            }
        }

        function sync() {
            var nextConfig = {
                version: 1,
                mode: "builder",
                source_device_type_id: currentDeviceType ? currentDeviceType.id : null,
                rows: parseInt(rowsInput.value, 10) || 2,
                columns: parseInt(columnsInput.value, 10) || 32,
                grid: grid,
            };
            input.value = JSON.stringify(nextConfig);
            cssPreview.textContent = cssFromConfig(nextConfig);
        }

        function applyDeviceType(deviceType) {
            currentDeviceType = deviceType;
            if (currentDeviceType) {
                var existingIndex = deviceTypes.findIndex(function (existing) { return existing.id === currentDeviceType.id; });
                if (existingIndex === -1) deviceTypes.push(currentDeviceType);
                else deviceTypes[existingIndex] = currentDeviceType;
                addDeviceTypeOption(currentDeviceType);
            }
            if (currentDeviceType) deviceTypeSelect.value = currentDeviceType.id;

            if (currentDeviceType) {
                rowsInput.value = currentDeviceType.rows || 2;
                if (currentDeviceType.front_image_url) {
                    image.src = currentDeviceType.front_image_url;
                    image.hidden = false;
                    imageEmpty.hidden = true;
                } else {
                    image.removeAttribute("src");
                    image.hidden = true;
                    imageEmpty.hidden = false;
                    var templateCount = (currentDeviceType.interfaces || []).length + (currentDeviceType.front_ports || []).length + (currentDeviceType.rear_ports || []).length + (currentDeviceType.console_ports || []).length;
                    imageEmpty.textContent = templateCount > 0
                        ? "No front-panel image is set for this reference device type."
                        : "This reference device type has no interface, port, or console templates to assign.";
                }
            } else {
                image.removeAttribute("src");
                image.hidden = true;
                imageEmpty.hidden = false;
                imageEmpty.textContent = "Select a reference device type to show its front-panel image.";
            }
            renderGrid();
        }

        function selectDeviceType(id) {
            currentDeviceType = deviceTypes.find(function (deviceType) { return String(deviceType.id) === String(id); }) || null;
            if (currentDeviceType && componentTemplateCount(currentDeviceType) > 0) {
                applyDeviceType(currentDeviceType);
                return;
            }
            if (!id) {
                applyDeviceType(null);
                return;
            }
            if (id && dataUrlTemplate && window.fetch) {
                image.hidden = true;
                imageEmpty.hidden = false;
                imageEmpty.textContent = "Loading reference device type...";
                var encodedId = encodeURIComponent(id);
                var url = dataUrlTemplate.replace("__device_type_id__", encodedId).replace(/\/0(?=\/)/, "/" + encodedId);
                fetch(url, {
                    credentials: "same-origin",
                    headers: { "Accept": "application/json" },
                })
                    .then(function (response) {
                        var contentType = response.headers.get("content-type") || "";
                        if (!response.ok) {
                            throw new Error("HTTP " + response.status + " loading " + url);
                        }
                        if (contentType.indexOf("application/json") === -1) {
                            throw new Error("Expected JSON but received " + (contentType || "unknown content type") + " from " + url);
                        }
                        return response.json();
                    })
                    .then(function (deviceType) {
                        if (deviceType) {
                            if (window.console) {
                                console.debug("Device View loaded layout data", {
                                    id: deviceType.id,
                                    interfaces: (deviceType.interfaces || []).length,
                                    front_ports: (deviceType.front_ports || []).length,
                                    rear_ports: (deviceType.rear_ports || []).length,
                                    console_ports: (deviceType.console_ports || []).length,
                                });
                            }
                            applyDeviceType(deviceType);
                        }
                        else {
                            applyDeviceType(null);
                            imageEmpty.textContent = "Could not load interface templates for the selected reference device type.";
                        }
                    })
                    .catch(function (error) {
                        applyDeviceType(null);
                        imageEmpty.textContent = "Could not load interface templates: " + error.message;
                        if (window.console) console.error("Device View layout data load failed", error);
                    });
                return;
            }
            applyDeviceType(null);
            imageEmpty.textContent = "Could not load interface templates: missing layout-data URL.";
        }

        root.querySelector("[data-autofill]").addEventListener("click", function () {
            if (!currentDeviceType) return;
            var interfaces = (currentDeviceType.interfaces || []).slice();
            if (root.querySelector("[data-reverse]").checked) interfaces.reverse();
            var startRow = selectedCell ? selectedCell.row : 0;
            var startColumn = selectedCell ? selectedCell.column : Math.max(1, parseInt(startColumnInput.value, 10) || 1) - 1;
            var selectedInterfaceIndex = interfaces.findIndex(function (iface) {
                return (iface.area || slugArea(iface.name, iface.id)) === cellTokenSelect.value;
            });
            if (selectedInterfaceIndex > 0) interfaces = interfaces.slice(selectedInterfaceIndex);
            var gapEvery = Math.max(0, parseInt(root.querySelector("[data-gap-every]").value, 10) || 0);
            var gapSize = Math.max(0, parseInt(root.querySelector("[data-gap-size]").value, 10) || 0);
            var rows = parseInt(rowsInput.value, 10) || 2;
            var columns = parseInt(columnsInput.value, 10) || 32;
            resizeGrid(rows, columns);

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
                        row = startRow;
                        column = startColumn + offset;
                    } else {
                        row = startRow + (offset % pairedRows);
                        column = startColumn + Math.floor(offset / pairedRows);
                    }
                }

                if (row < rows && column < columns) {
                    grid[row][column] = iface.area || slugArea(iface.name, iface.id);
                }
            });
            renderGrid();
        });

        root.querySelector("[data-fill-blanks]").addEventListener("click", function () {
            grid.forEach(function (row) {
                var firstUsed = row.findIndex(function (token) { return !isEmptyToken(token); });
                var lastUsed = row.length - 1;
                while (lastUsed >= 0 && isEmptyToken(row[lastUsed])) lastUsed -= 1;
                row.forEach(function (token, index) {
                    if (token && token !== ".") return;
                    if (firstUsed === -1 || index < firstUsed || index > lastUsed) row[index] = ".";
                    else row[index] = SPACE_TOKEN;
                });
            });
            renderGrid();
        });

        root.querySelector("[data-clear-grid]").addEventListener("click", function () {
            grid = [];
            selectedCell = null;
            renderGrid();
        });

        root.querySelectorAll("[data-pattern]").forEach(function (button) {
            button.addEventListener("click", function () {
                selectedPattern = button.getAttribute("data-pattern") || "paired";
                root.querySelectorAll("[data-pattern]").forEach(function (other) {
                    var active = other === button;
                    other.classList.toggle("active", active);
                    other.setAttribute("aria-pressed", active ? "true" : "false");
                });
            });
        });

        cellTokenSelect.addEventListener("change", function () {
            if (!selectedCell) return;
            grid[selectedCell.row][selectedCell.column] = cellTokenSelect.value;
            renderGrid();
        });

        columnsInput.addEventListener("change", renderGrid);
        deviceTypeSelect.addEventListener("change", function () { selectDeviceType(deviceTypeSelect.value); });

        if (config.mode === "builder") {
            grid = config.grid || [];
            columnsInput.value = config.columns || 32;
            if (config.source_device_type_id) deviceTypeSelect.value = config.source_device_type_id;
        }
        if (!deviceTypeSelect.value && defaultDeviceTypeId) deviceTypeSelect.value = defaultDeviceTypeId;
        selectDeviceType(deviceTypeSelect.value);
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-layout-builder]").forEach(initBuilder);
    });
}());
