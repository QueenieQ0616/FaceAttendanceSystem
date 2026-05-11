// static/js/activity_group.js
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('group-form');
  const statusEl = document.getElementById('group-status');
  const resultSection = document.getElementById('result-section');
  const resultSummary = document.getElementById('result-summary');
  const resultTbody = document.getElementById('result-tbody');
  const resultEmpty = document.getElementById('result-empty');
  const previewWrap = document.getElementById('preview-wrap');
  const submitBtn = document.getElementById('btn-submit');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    statusEl.textContent = '正在处理，请稍候…';
    resultSection.hidden = true;
    resultEmpty.hidden = true;

    const formData = new FormData(form);
    try {
      const resp = await fetch(window.GROUP_PHOTO_API_URL, {
        method: 'POST',
        body: formData,
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`服务器错误 (${resp.status}): ${text}`);
      }
      const json = await resp.json();
      if (!json.success) {
        throw new Error(json.message || '处理失败');
      }

      const data = json.data;
      statusEl.textContent = `处理完成：检测到 ${data.faces_detected} 张人脸，成功识别 ${data.faces_recognized} 人。`;
      resultSummary.textContent = `活动：${data.activity_name}，时间：${data.time}`;

      if (data.photo_path) {
        previewWrap.innerHTML = `<img src="/uploads/${data.photo_path}" class="preview-photo" alt="合照预览">`;
      } else {
        previewWrap.innerHTML = '';
      }

      resultTbody.innerHTML = '';
      if (data.matched && data.matched.length > 0) {
        data.matched.forEach(m => {
          const row = document.createElement('tr');
          row.innerHTML = `
            <td>${m.student_id}</td>
            <td>${m.name}</td>
            <td>${m.similarity}</td>
            <td>${m.emotion || '未识别'}</td>`;   // 显示情绪
          resultTbody.appendChild(row);
        });
        resultEmpty.hidden = true;
      } else {
        resultEmpty.hidden = false;
        resultTbody.innerHTML = '';
      }
      resultSection.hidden = false;
    } catch (err) {
      statusEl.textContent = `出错：${err.message}`;
      alert('照片处理失败：' + err.message);
    } finally {
      submitBtn.disabled = false;
    }
  });
});