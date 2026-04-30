/**
 * Notion 账号信息提取脚本
 *
 * 使用方法：
 * 1. 浏览器登录 https://www.notion.so/ai
 * 2. F12 → Application → Cookies → 复制 token_v2 的值
 * 3. F12 → Console → 粘贴本脚本 → 回车
 * 4. 查看列出的工作区，在弹窗中输入编号
 * 5. 把输出的 JSON 粘贴到 accounts.json，替换 YOUR_TOKEN_V2
 */
(async () => {
  try {
    const r = await fetch('/api/v3/loadUserContent', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: '{}', credentials: 'include'
    });
    const d = (await r.json()).recordMap || {};

    // 提取用户信息（遍历所有可能的字段路径）
    const uid = Object.keys(d.notion_user || {})[0] || '';
    const uRaw = d.notion_user?.[uid] || {};
    const u = uRaw.value?.value || uRaw.value || uRaw || {};
    const userName = u.given_name || u.name || u.family_name || u.profile?.given_name || '';
    const userEmail = u.email || u.profile?.email || '';

    // 提取所有工作区（深度搜索 name 字段）
    const spaces = Object.entries(d.space || {}).map(([id, raw]) => {
      // Notion 可能把数据放在 value、value.value、或直接在顶层
      const v1 = raw.value || raw;
      const v2 = v1.value || v1;
      const name = v2.name || v1.name || raw.name || '';
      const plan = v2.plan_type || v1.plan_type || v2.subscription_tier || v1.subscription_tier || '';
      return { space_id: id, name, plan };
    });

    // 关联 space_view_id
    const viewMap = {};
    Object.entries(d.space_view || {}).forEach(([vid, raw]) => {
      const sv = raw.value?.value || raw.value || raw;
      const sid = sv.space_id;
      if (sid) viewMap[sid] = vid;
    });
    spaces.forEach(s => { s.space_view_id = viewMap[s.space_id] || '' });

    if (spaces.length === 0) {
      console.error('❌ 未找到任何工作区，请确认已登录 Notion');
      return;
    }

    // ─── 展示工作区列表 ───
    console.log('\n');
    console.log('%c═══════════════════════════════════════════════', 'color:#00a699');
    console.log('%c  Notion 账号信息提取工具', 'font-size:15px;font-weight:bold;color:#00a699');
    console.log('%c═══════════════════════════════════════════════', 'color:#00a699');
    console.log('');
    console.log(`%c👤 用户: ${userName || '(未获取到)'} ${userEmail ? '(' + userEmail + ')' : ''}`, 'font-size:13px');
    console.log(`%c📂 找到 ${spaces.length} 个工作区：`, 'font-size:13px;font-weight:bold');
    console.log('');

    spaces.forEach((s, i) => {
      const label = s.name || `(ID: ${s.space_id.slice(0, 13)}...)`;
      const planStr = s.plan ? `  计划: ${s.plan}` : '';
      console.log(`%c  [${i}]  ${label}${planStr}`, 'font-size:13px;padding:2px 0');
    });

    console.log('');
    console.log('%c� 请查看上方工作区列表，3 秒后弹窗选择...', 'color:#ff9800;font-size:12px');

    // 只有一个工作区时自动选择
    let chosen;
    if (spaces.length === 1) {
      chosen = spaces[0];
      console.log('%c🎯 只有一个工作区，自动选择', 'color:#2196f3;font-weight:bold');
    } else {
      // 等 3 秒让用户看清列表
      await new Promise(resolve => setTimeout(resolve, 3000));

      const promptText = spaces.map((s, i) => {
        const label = s.name || `ID: ${s.space_id.slice(0, 13)}...`;
        return `[${i}] ${label}`;
      }).join('\n');

      const idx = prompt(`请输入你有 AI 功能的工作区编号：\n\n${promptText}\n\n输入编号 (0 ~ ${spaces.length - 1})：`);

      if (idx === null || idx.trim() === '') {
        console.log('%c⚠️ 已取消，请重新运行脚本', 'color:#ff9800');
        return;
      }
      chosen = spaces[parseInt(idx)];
      if (!chosen) {
        console.error(`❌ 编号 "${idx}" 无效，请重新运行脚本`);
        return;
      }
    }

    const account = {
      token_v2: 'YOUR_TOKEN_V2',
      space_id: chosen.space_id,
      user_id: uid,
      space_view_id: chosen.space_view_id,
      user_name: userName,
      user_email: userEmail
    };

    const json = JSON.stringify(account, null, 2);
    const chosenLabel = chosen.name || chosen.space_id.slice(0, 13) + '...';

    console.log('');
    console.log('%c═══════════════════════════════════════════════', 'color:#00c853');
    console.log(`%c✅ 已选择: ${chosenLabel}`, 'color:#00c853;font-weight:bold;font-size:14px');
    console.log('%c═══════════════════════════════════════════════', 'color:#00c853');
    console.log('');
    console.log(json);
    console.log('');
    console.log('%c⚠️  下一步：把 YOUR_TOKEN_V2 替换为你复制的 token_v2 值', 'color:#ff9800;font-weight:bold');
    console.log('%c   然后粘贴到 accounts.json 数组中', 'color:#ff9800');

    // 延迟复制避免失焦
    setTimeout(() => {
      navigator.clipboard.writeText(json)
        .then(() => console.log('%c📋 已自动复制到剪贴板', 'color:#00c853'))
        .catch(() => console.log('%c📋 请手动选中上方 JSON 复制', 'color:#ff9800'));
    }, 800);

  } catch (e) { console.error('❌ 提取失败:', e.message) }
})();
