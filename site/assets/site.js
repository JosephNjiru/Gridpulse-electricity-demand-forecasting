(function () {
  "use strict";
  var chart = document.getElementById("demo-chart");
  var status = document.getElementById("demo-status");
  var view = document.getElementById("demo-view");
  var model = document.getElementById("demo-model");
  var region = document.getElementById("demo-region");
  var actual = Array.from({length: 48}, function (_, i) { return 740 + 70 * Math.sin(i / 5) + 18 * Math.sin(i / 2.4); });
  function draw() {
    var aggregate = view.value === "aggregate";
    var forecast = actual.map(function (v, i) { return v + (aggregate ? 0 : 17 * Math.cos(i / 4) - 8); });
    document.getElementById("metric-mae").textContent = aggregate ? "Unavailable" : "42.8";
    document.getElementById("metric-rmse").textContent = aggregate ? "Unavailable" : "61.4";
    document.getElementById("metric-coverage").textContent = aggregate ? "Fold mean" : "48/48";
    status.textContent = aggregate ? "Synthetic aggregate view, metrics shown as unavailable until approved public evidence is available" : "Synthetic selected-fold trace, 48 half-hour leads";
    chart.innerHTML = "";
    var title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = aggregate ? "Synthetic aggregate interface example" : "Synthetic actual and forecast demand trace";
    chart.appendChild(title);
    if (aggregate) {
      var text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", "32"); text.setAttribute("y", "150"); text.setAttribute("fill", "#5c6b73"); text.textContent = "Aggregate empirical charts are withheld pending source-rights review.";
      chart.appendChild(text); return;
    }
    var line = function (values) { return values.map(function (v, i) { return (i ? "L" : "M") + (32 + i * 836 / 47) + " " + (260 - (v - 650) * .5); }).join(" "); };
    [["#1b6d73", actual, "Actual, synthetic"], ["#d46b4c", forecast, "Forecast, synthetic"]].forEach(function (item) {
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", line(item[1])); path.setAttribute("fill", "none"); path.setAttribute("stroke", item[0]); path.setAttribute("stroke-width", "3");
      if (item[0] === "#d46b4c") path.setAttribute("stroke-dasharray", "7 5");
      chart.appendChild(path);
      var label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", item[0] === "#1b6d73" ? "32" : "150"); label.setAttribute("y", "24"); label.setAttribute("fill", item[0]); label.textContent = item[2]; chart.appendChild(label);
    });
    document.getElementById("chart-table-summary").textContent = "The synthetic " + region.value + " " + model.value + " example has 48 half-hour leads. Actual and forecast values are illustrative and are not AEMO observations.";
  }
  [view, model, region, document.getElementById("demo-market")].forEach(function (control) { control.addEventListener("change", draw); });
  draw();
}());
