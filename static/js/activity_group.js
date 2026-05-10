(function () {
  var form = document.getElementById("group-form");
  var statusEl = document.getElementById("group-status");
  var resultSection = document.getElementById("result-section");
  var resultSummary = document.getElementById("result-summary");
  var resultTbody = document.getElementById("result-tbody");
  var resultEmpty = document.getElementById("result-empty");
  var previewWrap = document.getElementById("preview-wrap");
  var btn = document.getElementById("btn-submit");
  var apiUrl = window.GROUP_PHOTO_API_URL || "/api/activity-group-photo";

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  if (!form) return;

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var nameInput = document.getElementById("activity_name");
    var fileInput = document.getElementById("photo");
    var activityName = nameInput && nameInput.value ? nameInput.value.trim() : "";
    if (!activityName) {
      setStatus("请填写活动名称。");
      ApiUtils.showPageAlert("请填写活动名称后再上传。", "error");
      return;
    }
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      setStatus("请选择合照文件。");
      ApiUtils.showPageAlert("请选择要上传的合照文件。", "error");
      return;
    }
    ApiUtils.showPageAlert("", "");
    var fd = new FormData();
    fd.append("activity_name", activityName);
    fd.append("photo", fileInput.files[0]);
    if (btn) btn.disabled = true;
    setStatus("正在上传并识别，请稍候…");
    if (resultSection) resultSection.hidden = true;

    fetch(apiUrl, { method: "POST", body: fd })
      .then(ApiUtils.readJsonSafe)
      .then(function (r) {
        if (!r.readOk) {
          setStatus("上传失败：网络异常。");
          ApiUtils.showPageAlert("上传失败：无法连接服务器或请求被中断，请检查网络后重试。", "error");
          return;
        }
        if (!r.parseOk) {
          var t =
            "上传失败：服务器返回非 JSON（HTTP " +
            r.status +
            "），可能是服务异常或超时。请稍后重试。";
          setStatus(t);
          ApiUtils.showPageAlert(t, "error");
          return;
        }
        var body = r.body;
        if (!body || typeof body !== "object") {
          setStatus("响应无效。");
          ApiUtils.showPageAlert("服务器返回了无效数据。", "error");
          return;
        }
        if (!body.success) {
          var msg = ApiUtils.unifiedMessage(body, "识别失败");
          setStatus("失败：" + msg);
          ApiUtils.showPageAlert(msg, "error");
          return;
        }
        var d = body.data || {};
        ApiUtils.showPageAlert("", "");
        setStatus("处理完成。");
        if (resultSection) resultSection.hidden = false;
        if (resultSummary) {
          resultSummary.textContent =
            "活动：「" +
            (d.activity_name || "") +
            "」· 检测到人脸 " +
            (d.faces_detected != null ? d.faces_detected : 0) +
            " 张 · 识别成功 " +
            (d.faces_recognized != null ? d.faces_recognized : 0) +
            " 人 · 特征失败 " +
            (d.embedding_failures != null ? d.embedding_failures : 0) +
            " 张 · 时间 " +
            (d.time || "");
        }
        if (previewWrap && d.photo_path) {
          var src = "/uploads/" + d.photo_path;
          previewWrap.innerHTML =
            '<strong>已保存合照预览</strong><br><img class="preview-photo" src="' +
            src +
            '" alt="合照">';
        }
        if (resultTbody) resultTbody.innerHTML = "";
        var list = d.matched || [];
        if (list.length === 0) {
          if (resultEmpty) resultEmpty.hidden = false;
          ApiUtils.showPageAlert(
            "处理完成，但未识别到库中学生。可提高合照清晰度或检查人脸库是否已录入。",
            "info"
          );
        } else {
          if (resultEmpty) resultEmpty.hidden = true;
          list.forEach(function (m) {
            var tr = document.createElement("tr");
            tr.innerHTML =
              "<td>" +
              escapeHtml(m.student_id) +
              "</td><td>" +
              escapeHtml(m.name) +
              "</td><td>" +
              escapeHtml(String(m.similarity != null ? m.similarity : "")) +
              "</td>";
            resultTbody.appendChild(tr);
          });
        }
      })
      .catch(function (err) {
        var msg = err && err.message ? err.message : String(err);
        setStatus("请求失败：" + msg);
        ApiUtils.showPageAlert("上传或识别过程出错：" + msg, "error");
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  });

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
