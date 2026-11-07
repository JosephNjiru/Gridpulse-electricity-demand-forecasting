(function () {
  "use strict";

  var svgNamespace = "http://www.w3.org/2000/svg";
  var chart = document.getElementById("demo-chart");
  var status = document.getElementById("demo-status");
  var market = document.getElementById("demo-market");
  var region = document.getElementById("demo-region");
  var model = document.getElementById("demo-model");
  var view = document.getElementById("demo-view");
  var mae = document.getElementById("metric-mae");
  var rmse = document.getElementById("metric-rmse");
  var coverage = document.getElementById("metric-coverage");
  var summary = document.getElementById("chart-table-summary");
  var regions = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"];
  var nemModels = [
    { value: "day", label: "Previous day" },
    { value: "week", label: "Previous week" },
    { value: "arima", label: "R ARIMA(1,0,0)" }
  ];
  var waModels = [{ value: "day", label: "Previous dispatch day" }];

  function hash(text) {
    var value = 2166136261;
    for (var index = 0; index < text.length; index += 1) {
      value ^= text.charCodeAt(index);
      value = Math.imul(value, 16777619);
    }
    return (value >>> 0) / 4294967296;
  }

  function replaceOptions(element, options) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
    options.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      element.appendChild(option);
    });
  }

  function syncControls() {
    var isWa = market.value === "WA";
    var previousRegion = region.value;
    replaceOptions(region, isWa ? [{ value: "SWIS", label: "SWIS/WEM" }] : regions.map(function (item) {
      return { value: item, label: item };
    }));
    region.value = isWa ? "SWIS" : (regions.indexOf(previousRegion) >= 0 ? previousRegion : "NSW1");
    var previousModel = model.value;
    var available = isWa ? waModels : nemModels;
    replaceOptions(model, available);
    model.value = available.some(function (item) { return item.value === previousModel; }) ? previousModel : available[0].value;
    document.getElementById("region-label").firstChild.textContent = isWa ? "Market area" : "Region";
    draw();
  }

  function series() {
    var isWa = market.value === "WA";
    var length = isWa ? 288 : 48;
    var seed = hash(market.value + ":" + region.value);
    var baseline = isWa ? 420 + seed * 80 : 650 + seed * 180;
    var regionFactor = 0.78 + seed * 0.52;
    var actual = [];
    var forecast = [];
    for (var index = 0; index < length; index += 1) {
      var phase = index / (isWa ? 34 : 6) + seed * 0.7;
      var daily = Math.sin(phase) * (isWa ? 46 : 70);
      var secondary = Math.sin(index / (isWa ? 9 : 2.5)) * (isWa ? 12 : 18);
      var observed = baseline + daily + secondary;
      var error;
      if (model.value === "week") {
        error = Math.cos(index / 4) * 28 - 10;
      } else if (model.value === "arima") {
        error = Math.cos(index / 5) * 18 + Math.sin(index / 3) * 7;
      } else {
        error = Math.cos(index / (isWa ? 21 : 4)) * (isWa ? 15 : 17) - 8;
      }
      error *= regionFactor;
      actual.push(observed);
      forecast.push(observed + error);
    }
    return { actual: actual, forecast: forecast, interval: isWa ? 5 : 30 };
  }

  function metrics(actual, forecast) {
    var absolute = 0;
    var squared = 0;
    var bias = 0;
    var mapeTotal = 0;
    var mapeCount = 0;
    actual.forEach(function (value, index) {
      var error = forecast[index] - value;
      absolute += Math.abs(error);
      squared += error * error;
      bias += error;
      if (value > 0) {
        mapeTotal += Math.abs(error) / value;
        mapeCount += 1;
      }
    });
    return {
      mae: absolute / actual.length,
      rmse: Math.sqrt(squared / actual.length),
      bias: bias / actual.length,
      mape: mapeCount ? 100 * mapeTotal / mapeCount : null,
      mapeCount: mapeCount
    };
  }

  function svgElement(name, attributes, text) {
    var element = document.createElementNS(svgNamespace, name);
    Object.keys(attributes).forEach(function (key) { element.setAttribute(key, attributes[key]); });
    if (text) {
      element.textContent = text;
    }
    return element;
  }

  function drawChart(data, selectedView) {
    while (chart.firstChild) {
      chart.removeChild(chart.firstChild);
    }
    var title = selectedView === "aggregate" ? "Synthetic aggregate interface example" : "Synthetic actual and forecast demand trace";
    chart.appendChild(svgElement("title", { id: "chart-title" }, title));
    chart.appendChild(svgElement("desc", { id: "chart-desc" }, "Synthetic " + data.actual.length + "-step " + (data.interval === 5 ? "five-minute" : "half-hour") + " comparison."));
    if (selectedView === "aggregate") {
      chart.appendChild(svgElement("text", { x: 32, y: 150, fill: "#5c6b73" }, "Aggregate empirical charts are withheld pending source-rights review."));
      return;
    }
    var all = data.actual.concat(data.forecast);
    var low = Math.min.apply(Math, all);
    var high = Math.max.apply(Math, all);
    var padding = Math.max(20, (high - low) * 0.08);
    low -= padding;
    high += padding;
    var x = function (index) { return 42 + index * 816 / Math.max(1, data.actual.length - 1); };
    var y = function (value) { return 260 - (value - low) * 210 / Math.max(1, high - low); };
    var line = function (values) { return values.map(function (value, index) { return (index ? "L" : "M") + x(index) + " " + y(value); }).join(" "); };
    var tickCount = 4;
    chart.appendChild(svgElement("text", { x: 42, y: 16, fill: "#171717", "font-size": 13 }, "Demand (MW)"));
    for (var tick = 0; tick <= tickCount; tick += 1) {
      var tickValue = low + (high - low) * tick / tickCount;
      var tickY = y(tickValue);
      chart.appendChild(svgElement("line", { x1: 42, y1: tickY, x2: 858, y2: tickY, stroke: "#cfc4b6", "stroke-dasharray": "3 5" }));
      chart.appendChild(svgElement("text", { x: 4, y: tickY + 4, fill: "#5f5a54", "font-size": 12 }, Math.round(tickValue)));
    }
    chart.appendChild(svgElement("text", { x: 42, y: 286, fill: "#5f5a54", "font-size": 12 }, "Lead 1"));
    chart.appendChild(svgElement("text", { x: 800, y: 286, fill: "#5f5a54", "font-size": 12 }, "Lead " + data.actual.length));
    chart.appendChild(svgElement("text", { x: 410, y: 298, fill: "#5f5a54", "font-size": 12 }, data.interval === 5 ? "Five-minute forecast lead" : "Half-hour forecast lead"));
    chart.appendChild(svgElement("path", { d: line(data.actual), fill: "none", stroke: "#315aa6", "stroke-width": 3 }));
    chart.appendChild(svgElement("path", { d: line(data.forecast), fill: "none", stroke: "#9e332d", "stroke-width": 3, "stroke-dasharray": "7 5" }));
    chart.appendChild(svgElement("text", { x: 42, y: 34, fill: "#315aa6", "font-size": 12 }, "Actual, synthetic"));
    chart.appendChild(svgElement("text", { x: 180, y: 34, fill: "#9e332d", "font-size": 12 }, "Forecast, synthetic"));
  }

  function draw() {
    var data = series();
    var result = metrics(data.actual, data.forecast);
    var aggregate = view.value === "aggregate";
    var unit = market.value === "WA" ? "five-minute" : "half-hour";
    mae.textContent = aggregate ? "Unavailable" : result.mae.toFixed(2);
    rmse.textContent = aggregate ? "Unavailable" : result.rmse.toFixed(2);
    coverage.textContent = aggregate ? "Fold mean" : data.actual.length + "/" + data.actual.length;
    status.textContent = aggregate
      ? "Synthetic aggregate view, empirical metrics are unavailable on this public site"
      : "Synthetic " + (market.value === "WA" ? "WA" : "NEM") + " selected-fold teaching scenario, " + data.actual.length + " " + unit + " leads";
    summary.textContent = aggregate
      ? "Aggregate empirical metrics are not included in this public demonstration. The underlying synthetic teaching scenario uses " + data.actual.length + " " + unit + " leads."
      : "The synthetic " + region.value + " " + model.options[model.selectedIndex].textContent + " example has " + data.actual.length + " " + unit + " leads. MAE is " + result.mae.toFixed(2) + " MW, RMSE is " + result.rmse.toFixed(2) + " MW, bias is " + result.bias.toFixed(2) + " MW, and MAPE eligibility is " + result.mapeCount + "/" + data.actual.length + ". Values are illustrative and are not AEMO observations.";
    drawChart(data, view.value);
  }

  market.addEventListener("change", syncControls);
  region.addEventListener("change", draw);
  model.addEventListener("change", draw);
  view.addEventListener("change", draw);
  syncControls();
}());
