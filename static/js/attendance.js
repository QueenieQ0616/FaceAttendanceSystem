(function () {
  var video = document.getElementById("cam-preview");
  var canvas = document.getElementById("cam-canvas");
  var btnStart = document.getElementById("btn-start");
  var btnCapture = document.getElementById("btn-capture");
  var btnStop = document.getElementById("btn-stop");
  var btnRefreshChallenge = document.getElementById("btn-refresh-challenge");
  var statusEl = document.getElementById("cam-status");
  var resultPanel = document.getElementById("result-panel");
  var historyList = document.getElementById("history-list");
  var promptEl = document.getElementById("liveness-prompt");
  var stream = null;
  var captureTimer = null;
  var apiUrl = window.ATTENDANCE_API_URL || "/api/attendance/capture";
  var challengeUrl = window.LIVENESS_CHALLENGE_URL || "/api/attendance/liveness-challenge";
  var currentAction = "blink";
  var currentPrompt = "";

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function clearCaptureTimer() {
    if (captureTimer) {
      clearInterval(captureTimer);
      captureTimer = null;
    }
  }

  function stopCamera() {
    clearCaptureTimer();
    if (stream) {
      stream.getTracks().forEach(function (t) {
        t.stop();
      });
      stream = null;
    }
    if (video) video.srcObject = null;
    if (btnCapture) btnCapture.disabled = true;
    if (btnStop) btnStop.disabled = true;
    setStatus("摄像头已停止。");
  }

  /** 将统一 JSON 转为旧版 renderResult 使用的扁平结构 */
  function normalizeCaptureBody(body) {
    if (!body || typeof body !== "object") {
      return { ok: false, message: "服务器返回了无效数据。" };
    }
    if (body.success === true && body.data && typeof body.data === "object") {
      var d = body.data;
      return {
        ok: true,
        success: true,
        code: body.code,
        message: body.message,
        liveness_passed: d.liveness_passed,
        liveness_result: d.liveness_result,
        liveness_detail: d.liveness_detail,
        recognized: d.recognized === true,
        student_id: d.student_id,
        name: d.name,
        time: d.time,
        status: d.status,
        similarity: d.similarity,
        dominant_emotion: d.dominant_emotion,
        emotion: d.emotion,
        action: d.action,
      };
    }
    if (body.success === false) {
      var d2 = body.data && typeof body.data === "object" ? body.data : {};
      return {
        ok: false,
        success: false,
        code: body.code,
        message: ApiUtils.unifiedMessage(body, "请求失败"),
        liveness_passed: d2.liveness_passed,
        liveness_result: d2.liveness_result,
        liveness_detail: d2.liveness_detail,
        recognized: d2.recognized === true,
        similarity: d2.similarity,
        time: d2.time,
        action: d2.action,
      };
    }
    return { ok: false, message: "非预期的接口响应格式。" };
  }

  function loadChallenge() {
    return fetch(challengeUrl)
      .then(ApiUtils.readJsonSafe)
      .then(function (r) {
        if (!r.readOk) {
          if (promptEl) promptEl.textContent = "网络异常，无法获取动作说明。";
          ApiUtils.showPageAlert("无法连接服务器获取活体指令，请检查网络后刷新页面。", "error");
          return;
        }
        if (!r.parseOk) {
          if (promptEl) promptEl.textContent = "服务器返回非 JSON，无法解析动作说明。";
          ApiUtils.showPageAlert(
            "获取活体指令失败（HTTP " + r.status + "）：响应不是有效的 JSON。",
            "error"
          );
          return;
        }
        var b = r.body;
        if (!b || !b.success || !b.data) {
          var msg = b ? ApiUtils.unifiedMessage(b, "获取失败") : "空响应";
          if (promptEl) promptEl.textContent = msg;
          ApiUtils.showPageAlert(msg, "error");
          return;
        }
        ApiUtils.showPageAlert("", "");
        currentAction = b.data.action || "blink";
        currentPrompt = b.data.prompt || "请按系统提示完成动作。";
        if (promptEl) promptEl.textContent = currentPrompt;
        setStatus("已更新活体动作说明，请阅读上方提示。");
      })
      .catch(function (err) {
        if (promptEl) promptEl.textContent = "无法获取动作说明，请刷新页面。";
        ApiUtils.showPageAlert(ApiUtils.cameraHumanError(err) || "加载活体指令失败。", "error");
      });
  }

  if (btnRefreshChallenge) {
    btnRefreshChallenge.addEventListener("click", function () {
      loadChallenge();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadChallenge);
  } else {
    loadChallenge();
  }

  if (btnStart) {
    btnStart.addEventListener("click", function () {
      ApiUtils.showPageAlert("", "");
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        var t = "当前浏览器不支持摄像头采集（缺少 getUserMedia），请使用 Chrome 或 Edge 等现代浏览器。";
        setStatus(t);
        ApiUtils.showPageAlert(t, "error");
        return;
      }
      setStatus("正在请求摄像头权限…");
      navigator.mediaDevices
        .getUserMedia({
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        })
        .then(function (s) {
          stream = s;
          video.srcObject = s;
          return video.play();
        })
        .then(function () {
          if (btnCapture) btnCapture.disabled = false;
          if (btnStop) btnStop.disabled = false;
          setStatus("摄像头已就绪。阅读上方动作提示后，点击「开始活体采集并考勤」。");
        })
        .catch(function (err) {
          var human = ApiUtils.cameraHumanError(err);
          setStatus("无法打开摄像头：" + human);
          ApiUtils.showPageAlert(human, "error");
        });
    });
  }

  if (btnStop) {
    btnStop.addEventListener("click", function () {
      stopCamera();
    });
  }

  function badgeTitleForFailure(data) {
    var c = data.code || "";
    if (c === "NO_FACE") return "未检测到人脸";
    if (c === "FACE_NOT_RECOGNIZED") return "人脸识别未匹配";
    return "考勤未成功";
  }

  function renderResult(rawBody) {
    if (!resultPanel) return;
    var data = normalizeCaptureBody(rawBody);
    resultPanel.classList.remove("muted");
    if (!data.ok) {
      resultPanel.innerHTML =
        "<p class=\"liv-badge fail\">请求失败</p><p>" +
        escapeHtml(data.message || "未知错误") +
        "</p>";
      resultPanel.classList.add("result-error");
      resultPanel.classList.remove("result-ok");
      ApiUtils.showPageAlert(data.message || "请求失败", "error");
      return;
    }

    if (data.liveness_passed === false) {
      resultPanel.classList.add("result-error");
      resultPanel.classList.remove("result-ok");
      resultPanel.innerHTML =
        "<p class=\"liv-badge fail\">活体检测：失败</p>" +
        "<p>" +
        escapeHtml(data.liveness_detail || data.message || "未通过动作活体。") +
        "</p>" +
        "<p class=\"muted small\">本次不会写入考勤记录。</p>";
      ApiUtils.showPageAlert(data.liveness_detail || data.message || "活体检测未通过。", "error");
      return;
    }

    if (data.liveness_passed === true && data.recognized) {
      resultPanel.classList.add("result-ok");
      resultPanel.classList.remove("result-error");
      ApiUtils.showPageAlert("", "");
      resultPanel.innerHTML =
        "<p class=\"liv-badge pass\">活体检测：通过</p>" +
        "<ul class=\"result-lines\">" +
        "<li><strong>姓名</strong>：" +
        escapeHtml(data.name || "") +
        "</li>" +
        "<li><strong>学号</strong>：" +
        escapeHtml(data.student_id || "") +
        "</li>" +
        "<li><strong>考勤时间</strong>：" +
        escapeHtml(data.time || "") +
        "</li>" +
        "<li><strong>考勤状态</strong>：" +
        escapeHtml(data.status || "") +
        "</li>" +
        "<li><strong>相似度</strong>：" +
        escapeHtml(String(data.similarity != null ? data.similarity : "")) +
        "</li>" +
        "<li><strong>活体结果</strong>：" +
        escapeHtml(data.liveness_result || "") +
        "</li>" +
        "<li><strong>主导情绪（DeepFace）</strong>：" +
        escapeHtml(data.dominant_emotion || data.emotion || "—") +
        "</li>" +
        "</ul>";
      return;
    }

    if (data.liveness_passed === true && !data.recognized) {
      resultPanel.classList.remove("result-ok");
      resultPanel.classList.add("result-error");
      var title = badgeTitleForFailure(data);
      resultPanel.innerHTML =
        "<p class=\"liv-badge fail\">" +
        escapeHtml(title) +
        "</p>" +
        "<p>" +
        escapeHtml(data.message || "未识别到库中学生或未检测到清晰人脸。") +
        "</p>" +
        (data.similarity != null
          ? "<p class=\"muted small\">相似度参考：" + escapeHtml(String(data.similarity)) + "</p>"
          : "") +
        "<p class=\"muted small\">未写入考勤记录。</p>";
      ApiUtils.showPageAlert(data.message || title, "error");
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function appendHistory(summary, ok) {
    if (!historyList) return;
    var li = document.createElement("li");
    li.className = ok ? "history-ok" : "history-fail";
    li.textContent = summary;
    historyList.insertBefore(li, historyList.firstChild);
  }

  function submitFrames(frames) {
    setStatus("正在上传并分析活体与人脸…");
    fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: currentAction, frames: frames }),
    })
      .then(ApiUtils.readJsonSafe)
      .then(function (r) {
        if (!r.readOk) {
          renderResult({ success: false, message: "网络异常，未收到服务器响应。" });
          appendHistory("网络错误", false);
          ApiUtils.showPageAlert("上传失败：网络异常。", "error");
          return;
        }
        if (!r.parseOk) {
          var hint =
            "上传失败：服务器返回非 JSON（HTTP " +
            r.status +
            "）。可能是网关超时或服务异常。";
          renderResult({ success: false, message: hint });
          appendHistory("解析响应失败", false);
          ApiUtils.showPageAlert(hint, "error");
          return;
        }
        var body = r.body;
        renderResult(body);
        var flat = normalizeCaptureBody(body);
        if (!flat.ok) {
          appendHistory("失败：" + (flat.message || r.status), false);
          return;
        }
        if (flat.liveness_passed === false) {
          appendHistory(
            (flat.time || "") + " · 活体失败 · " + (flat.liveness_detail || flat.message || ""),
            false
          );
        } else if (flat.recognized) {
          appendHistory(
            (flat.time || "") +
              " · 活体通过 · " +
              (flat.name || "") +
              "（" +
              (flat.student_id || "") +
              "）",
            true
          );
        } else {
          appendHistory((flat.time || "") + " · 活体通过 · 未识别 · " + (flat.message || ""), false);
        }
      })
      .catch(function (err) {
        var msg = err && err.message ? err.message : String(err);
        renderResult({ success: false, message: msg });
        appendHistory("网络或客户端错误", false);
        ApiUtils.showPageAlert("提交考勤数据失败：" + msg, "error");
      })
      .finally(function () {
        clearCaptureTimer();
        if (stream && btnCapture) btnCapture.disabled = false;
        setStatus(stream ? "可再次采集，或先刷新动作说明。" : "");
      });
  }

  if (btnCapture) {
    btnCapture.addEventListener("click", function () {
      if (!stream || !video.videoWidth) {
        setStatus("请先启动摄像头并等待画面。");
        ApiUtils.showPageAlert("请先点击「启动摄像头」并等待预览画面出现后再采集。", "error");
        return;
      }
      var w = video.videoWidth;
      var h = video.videoHeight;
      canvas.width = w;
      canvas.height = h;
      var ctx = canvas.getContext("2d");
      var frames = [];
      btnCapture.disabled = true;
      ApiUtils.showPageAlert("", "");
      setStatus("正在采集多帧（约 3 秒），请按上方提示完成眨眼或张嘴…");
      var t0 = Date.now();
      function grab() {
        ctx.drawImage(video, 0, 0, w, h);
        frames.push(canvas.toDataURL("image/jpeg", 0.8));
      }
      grab();
      captureTimer = setInterval(function () {
        grab();
        if (Date.now() - t0 >= 3000) {
          clearCaptureTimer();
          submitFrames(frames);
        }
      }, 200);
    });
  }

  window.addEventListener("beforeunload", function () {
    stopCamera();
  });
})();
