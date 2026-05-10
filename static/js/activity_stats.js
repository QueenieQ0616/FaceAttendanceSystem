(function () {
  function initChart() {
    var dom = document.getElementById("activity-chart");
    var rawEl = document.getElementById("stats-data");
    if (!dom || typeof echarts === "undefined") return;
    var data = [];
    try {
      data = JSON.parse((rawEl && rawEl.textContent) || "[]");
    } catch (e) {
      dom.innerHTML = "<p class=\"muted\">图表数据解析失败。</p>";
      return;
    }
    if (!data.length) {
      dom.innerHTML = "<p class=\"muted\">暂无数据，无法绘制图表。</p>";
      return;
    }
    var labels = data.map(function (d) {
      return d.label || d.student_id;
    });
    var values = data.map(function (d) {
      return d.cnt;
    });
    var chart = echarts.init(dom);
    chart.setOption({
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: function (params) {
          var p = params[0];
          var i = p.dataIndex;
          var row = data[i] || {};
          return (
            (row.title || row.name || "") +
            "<br/>参与次数：<strong>" +
            p.value +
            "</strong>"
          );
        },
      },
      grid: { left: "3%", right: "4%", bottom: "14%", top: "8%", containLabel: true },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { rotate: 40, interval: 0, fontSize: 10 },
        name: "学号",
        nameLocation: "middle",
        nameGap: 36,
      },
      yAxis: {
        type: "value",
        name: "参与次数",
        minInterval: 1,
      },
      dataZoom: [
        { type: "inside", xAxisIndex: 0, start: 0, end: Math.min(100, (12 / labels.length) * 100) },
        { type: "slider", xAxisIndex: 0, height: 22, bottom: 8, start: 0, end: Math.min(100, (12 / labels.length) * 100) },
      ],
      series: [
        {
          name: "活动参与次数",
          type: "bar",
          data: values,
          itemStyle: { color: "#2563eb" },
          barMaxWidth: 48,
        },
      ],
    });
    window.addEventListener("resize", function () {
      chart.resize();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChart);
  } else {
    initChart();
  }
})();
