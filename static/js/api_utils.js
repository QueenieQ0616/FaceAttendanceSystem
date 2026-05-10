/**
 * 统一 API 响应：{ success, code, message, data }
 */
(function () {
  function readJsonSafe(res) {
    return res.text().then(function (text) {
      var parsed = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch (e) {
        return {
          readOk: true,
          parseOk: false,
          httpOk: res.ok,
          status: res.status,
          body: null,
          rawText: text,
          parseError: String(e.message || e),
        };
      }
      return {
        readOk: true,
        parseOk: true,
        httpOk: res.ok,
        status: res.status,
        body: parsed,
        rawText: text,
        parseError: null,
      };
    });
  }

  function unifiedMessage(body, fallback) {
    if (body && typeof body.message === "string" && body.message.trim()) {
      return body.message.trim();
    }
    return fallback || "未知错误";
  }

  function cameraHumanError(err) {
    if (!err) return "无法打开摄像头。";
    var name = err.name || "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return "浏览器已拒绝摄像头权限，请在地址栏旁点击允许后刷新页面重试。";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return "未检测到摄像头设备，请连接摄像头或使用带摄像头的设备。";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "摄像头无法打开（可能被其他程序占用），请关闭占用摄像头的应用后重试。";
    }
    if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
      return "当前摄像头不满足采集参数，可尝试更换浏览器或降低分辨率要求。";
    }
    if (name === "SecurityError") {
      return "安全限制：请使用 HTTPS，或通过 localhost / 127.0.0.1 访问本系统。";
    }
    if (name === "AbortError") {
      return "摄像头请求已中断，请重试。";
    }
    return err.message ? String(err.message) : String(err);
  }

  function showPageAlert(message, kind) {
    var el = document.getElementById("page-alert");
    if (!el) return;
    if (!message) {
      el.hidden = true;
      el.textContent = "";
      el.className = "page-alert";
      return;
    }
    el.hidden = false;
    el.textContent = message;
    el.className = "page-alert page-alert--" + (kind || "error");
  }

  window.ApiUtils = {
    readJsonSafe: readJsonSafe,
    unifiedMessage: unifiedMessage,
    cameraHumanError: cameraHumanError,
    showPageAlert: showPageAlert,
  };
})();
