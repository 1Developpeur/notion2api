/**
 * Notion text
 *
 * text `python login.py`text Chrome/Edge
 * text token_v2 text/text
 *
 * text
 * 1. text https://www.notion.so/ai
 * 2. text
 * 3. F12 → Application → Cookies → text token_v2 text
 * 4. F12 → Console → text → text
 * 5. text/text
 * 6. text JSON text accounts.jsontext YOUR_TOKEN_V2
 */
(async () => {
  try {
    // ─── text 1 text ───
    // getSpaces text token text
    let allUsers = {};  // user_id → {name, email}
    let allSpaces = {}; // space_id → {name, plan, members}
    let spaceViewMap = {}; // space_id → space_view_id

    // text getSpacestext
    try {
      const r1 = await fetch('/api/v3/getSpaces', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: '{}', credentials: 'include'
      });
      const d1 = await r1.json();
      // getSpaces text { "user_id_1": { space: {...}, ... }, "user_id_2": {...} }
      if (d1 && typeof d1 === 'object' && !d1.recordMap) {
        for (const [userId, userData] of Object.entries(d1)) {
          if (!userData || typeof userData !== 'object') continue;
          // text
          const nu = userData.notion_user;
          if (nu) {
            for (const [nuid, nuData] of Object.entries(nu)) {
              const v = nuData?.value?.value || nuData?.value || nuData || {};
              allUsers[nuid] = {
                name: v.given_name || v.name || v.family_name || '',
                email: v.email || ''
              };
            }
          }
          // text
          const sp = userData.space;
          if (sp) {
            for (const [sid, sData] of Object.entries(sp)) {
              const v = sData?.value?.value || sData?.value || sData || {};
              if (!allSpaces[sid]) {
                allSpaces[sid] = {
                  name: v.name || '',
                  plan: v.plan_type || v.subscription_tier || ''
                };
              }
            }
          }
          // text space_view
          const sv = userData.space_view;
          if (sv) {
            for (const [svid, svData] of Object.entries(sv)) {
              const v = svData?.value?.value || svData?.value || svData || {};
              if (v.space_id) spaceViewMap[v.space_id] = svid;
            }
          }
        }
      }
    } catch (e) { /* getSpaces textfallback text loadUserContent */ }

    // fallbacktextloadUserContent
    const r2 = await fetch('/api/v3/loadUserContent', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: '{}', credentials: 'include'
    });
    const d2 = (await r2.json()).recordMap || {};

    // text
    for (const [nuid, nuData] of Object.entries(d2.notion_user || {})) {
      if (allUsers[nuid]) continue;
      const v = nuData?.value?.value || nuData?.value || nuData || {};
      allUsers[nuid] = {
        name: v.given_name || v.name || v.family_name || '',
        email: v.email || ''
      };
    }
    // text
    for (const [sid, sData] of Object.entries(d2.space || {})) {
      if (allSpaces[sid]) continue;
      const v = sData?.value?.value || sData?.value || sData || {};
      allSpaces[sid] = {
        name: v.name || '',
        plan: v.plan_type || v.subscription_tier || ''
      };
    }
    // text space_view
    for (const [svid, svData] of Object.entries(d2.space_view || {})) {
      const v = svData?.value?.value || svData?.value || svData || {};
      if (v.space_id && !spaceViewMap[v.space_id]) spaceViewMap[v.space_id] = svid;
    }

    // text cookie text notion_user_idtext UI text
    const cookieUserId = document.cookie.split(';')
      .map(c => c.trim())
      .find(c => c.startsWith('notion_user_id='))
      ?.split('=')[1] || '';

    const userList = Object.entries(allUsers);
    const spaceList = Object.entries(allSpaces).map(([id, s]) => ({
      space_id: id, name: s.name, plan: s.plan, space_view_id: spaceViewMap[id] || ''
    }));

    if (userList.length === 0) {
      console.error('❌ text Notion');
      return;
    }

    // ─── text & text ───
    console.log('\n');
    console.log('%c═══════════════════════════════════════════════', 'color:#00a699');
    console.log('%c  Notion text', 'font-size:15px;font-weight:bold;color:#00a699');
    console.log('%c═══════════════════════════════════════════════', 'color:#00a699');
    console.log('');

    let chosenUserId, chosenUserName, chosenUserEmail;

    if (userList.length === 1) {
      chosenUserId = userList[0][0];
      chosenUserName = userList[0][1].name;
      chosenUserEmail = userList[0][1].email;
      console.log(`%c👤 text: ${chosenUserName || '(text)'} ${chosenUserEmail ? '(' + chosenUserEmail + ')' : ''}`, 'font-size:13px');
    } else {
      console.log(`%c👥 text ${userList.length} text Notion text`, 'font-size:13px;font-weight:bold');
      console.log('');
      userList.forEach(([uid, u], i) => {
        const active = uid === cookieUserId ? ' ← text' : '';
        console.log(`%c  [${i}]  ${u.name || '(text)'} ${u.email ? '(' + u.email + ')' : ''}${active}`, 'font-size:13px');
      });
      console.log('');
      console.log('%c👆 text3 text...', 'color:#ff9800;font-size:12px');

      await new Promise(resolve => setTimeout(resolve, 3000));

      const promptText = userList.map(([uid, u], i) => {
        const active = uid === cookieUserId ? ' ← text' : '';
        return `[${i}] ${u.name || '(text)'} ${u.email ? '(' + u.email + ')' : ''}${active}`;
      }).join('\n');

      const idx = prompt(`text\n\n${promptText}\n\ntext (0 ~ ${userList.length - 1})text`);
      if (idx === null || idx.trim() === '') {
        console.log('%c⚠️ text', 'color:#ff9800');
        return;
      }
      const chosen = userList[parseInt(idx)];
      if (!chosen) {
        console.error(`❌ text "${idx}" text`);
        return;
      }
      chosenUserId = chosen[0];
      chosenUserName = chosen[1].name;
      chosenUserEmail = chosen[1].email;
    }

    console.log(`%c✅ text: ${chosenUserName || chosenUserId.slice(0,8)} ${chosenUserEmail ? '(' + chosenUserEmail + ')' : ''}`, 'color:#00c853;font-size:13px');

    // ─── text ───
    if (spaceList.length === 0) {
      console.error('❌ text');
      return;
    }

    console.log('');
    console.log(`%c📂 text ${spaceList.length} text`, 'font-size:13px;font-weight:bold');
    console.log('');
    spaceList.forEach((s, i) => {
      const label = s.name || `(ID: ${s.space_id.slice(0, 13)}...)`;
      const planStr = s.plan ? `  text: ${s.plan}` : '';
      console.log(`%c  [${i}]  ${label}${planStr}`, 'font-size:13px');
    });

    let chosenSpace;
    if (spaceList.length === 1) {
      chosenSpace = spaceList[0];
      console.log('%c🎯 text', 'color:#2196f3;font-weight:bold');
    } else {
      console.log('');
      console.log('%c👆 3 text...', 'color:#ff9800;font-size:12px');
      await new Promise(resolve => setTimeout(resolve, 3000));

      const promptText = spaceList.map((s, i) => {
        const label = s.name || `ID: ${s.space_id.slice(0, 13)}...`;
        return `[${i}] ${label}`;
      }).join('\n');

      const idx = prompt(`text AI text\n\n${promptText}\n\ntext (0 ~ ${spaceList.length - 1})text`);
      if (idx === null || idx.trim() === '') {
        console.log('%c⚠️ text', 'color:#ff9800');
        return;
      }
      chosenSpace = spaceList[parseInt(idx)];
      if (!chosenSpace) {
        console.error(`❌ text "${idx}" text`);
        return;
      }
    }

    // ─── text ───
    const account = {
      token_v2: 'YOUR_TOKEN_V2',
      space_id: chosenSpace.space_id,
      user_id: chosenUserId,
      space_view_id: chosenSpace.space_view_id,
      user_name: chosenUserName,
      user_email: chosenUserEmail
    };

    const json = JSON.stringify(account, null, 2);
    const spaceLabel = chosenSpace.name || chosenSpace.space_id.slice(0, 13) + '...';

    console.log('');
    console.log('%c═══════════════════════════════════════════════', 'color:#00c853');
    console.log(`%c✅ text: ${chosenUserName || '(text)'}  text: ${spaceLabel}`, 'color:#00c853;font-weight:bold;font-size:14px');
    console.log('%c═══════════════════════════════════════════════', 'color:#00c853');
    console.log('');
    console.log(json);
    console.log('');
    console.log('%c⚠️  text YOUR_TOKEN_V2 text token_v2 text', 'color:#ff9800;font-weight:bold');
    console.log('%c   text accounts.json text', 'color:#ff9800');
    console.log('%c   ⚠️  texttoken_v2 text Cookies text', 'color:#ff9800');

    setTimeout(() => {
      navigator.clipboard.writeText(json)
        .then(() => console.log('%c📋 text', 'color:#00c853'))
        .catch(() => console.log('%c📋 text JSON text', 'color:#ff9800'));
    }, 800);

  } catch (e) { console.error('❌ text:', e.message) }
})();
