/**
 * 小说工坊 · Client 半（Web GUI 面板）
 *
 * 纯 JS + React.createElement（模板要求，无构建步骤）。
 * 数据全部来自同源 `/novel-forge/api`，由插件 Host 半提供；
 * 不读宿主 DOM、不用 iframe，颜色只用 --dsw-alias-* 主题变量。
 */
window.__ModuleLoader__.load({
  id: '@local/dsh-novel-forge',
  factory(require) {
    const React = require('react');
    const { useState, useEffect, useCallback } = React;
    const h = React.createElement;

    const CSS = `
.nf-root{height:100%;min-height:0;display:flex;flex-direction:column;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-size:13px;line-height:1.55;font-family:inherit}
.nf-head{display:flex;align-items:center;gap:12px;padding:14px 22px;border-bottom:1px solid var(--dsw-alias-border-l1);flex:0 0 auto}
.nf-logo{width:30px;height:30px;flex:0 0 auto;color:var(--dsw-alias-brand-primary)}
.nf-title{font-size:15px;font-weight:600;letter-spacing:.2px}
.nf-sub{color:var(--dsw-alias-label-secondary);font-size:12px;margin-top:1px}
.nf-spacer{flex:1}
.nf-btn{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:7px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);cursor:pointer;font-size:12px;font-family:inherit}
.nf-btn:hover{background:var(--dsw-alias-bg-layer-2)}
.nf-btn.primary{background:var(--dsw-alias-brand-primary);border-color:transparent;color:#fff}
.nf-btn:disabled{opacity:.55;cursor:not-allowed}
.nf-tabs{display:flex;gap:4px;padding:8px 22px;border-bottom:1px solid var(--dsw-alias-border-l1);flex:0 0 auto;flex-wrap:wrap}
.nf-tab{padding:5px 12px;border-radius:7px;color:var(--dsw-alias-label-secondary);cursor:pointer;font-size:12.5px;border:1px solid transparent;background:transparent;font-family:inherit}
.nf-tab:hover{background:var(--dsw-alias-bg-layer-1)}
.nf-tab.on{background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);border-color:var(--dsw-alias-border-l1)}
.nf-body{flex:1;min-height:0;overflow:auto;padding:16px 22px 28px}
.nf-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.nf-card{background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:9px;padding:12px 14px;margin-bottom:12px}
.nf-card h3{margin:0 0 8px;font-size:13px;font-weight:600}
.nf-stat{font-size:19px;font-weight:650;letter-spacing:.3px}
.nf-stat-label{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:1px}
.nf-muted{color:var(--dsw-alias-label-secondary)}
.nf-dim{display:flex;align-items:center;gap:8px;margin:6px 0}
.nf-dim-name{width:80px;font-size:12px;color:var(--dsw-alias-label-secondary);flex:0 0 auto}
.nf-bar{flex:1;height:7px;border-radius:4px;background:var(--dsw-alias-bg-layer-2);overflow:hidden}
.nf-bar>i{display:block;height:100%;border-radius:4px;background:var(--dsw-alias-brand-primary)}
.nf-score{width:38px;text-align:right;font-variant-numeric:tabular-nums;font-size:12px}
.nf-table{width:100%;border-collapse:collapse;font-size:12px}
.nf-table th,.nf-table td{padding:5px 8px;border-bottom:1px solid var(--dsw-alias-border-l1);text-align:left;vertical-align:top}
.nf-table th{color:var(--dsw-alias-label-secondary);font-weight:500}
.nf-table tr:last-child td{border-bottom:none}
.nf-find{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:10px 12px;margin-bottom:10px;background:var(--dsw-alias-bg-layer-1)}
.nf-find-h{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.nf-badge{font-size:11px;padding:1px 7px;border-radius:10px;border:1px solid var(--dsw-alias-border-l2);color:var(--dsw-alias-label-secondary);white-space:nowrap}
.nf-badge.hard{color:var(--dsw-alias-state-error-primary);border-color:var(--dsw-alias-state-error-primary)}
.nf-badge.warn{color:var(--dsw-alias-state-warn-primary);border-color:var(--dsw-alias-state-warn-primary)}
.nf-loc{font-weight:600;font-size:12px}
.nf-q{margin:4px 0;padding:6px 9px;border-left:2px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-2);border-radius:0 6px 6px 0;white-space:pre-wrap;word-break:break-word;font-size:12px}
.nf-why{font-size:12px;margin:3px 0}
.nf-why b{font-weight:600}
.nf-actions{display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap}
.nf-check{display:flex;gap:5px;align-items:center;font-size:12px;cursor:pointer;user-select:none}
.nf-textarea{width:100%;box-sizing:border-box;min-height:54px;resize:vertical;border:1px solid var(--dsw-alias-border-l2);border-radius:7px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);padding:7px 9px;font-size:12px;font-family:inherit}
.nf-empty{padding:28px;text-align:center;color:var(--dsw-alias-label-secondary);border:1px dashed var(--dsw-alias-border-l1);border-radius:10px}
.nf-err{color:var(--dsw-alias-state-error-primary);font-size:12px;margin:8px 0;white-space:pre-wrap}
.nf-ok{color:var(--dsw-alias-state-success-primary)}
.nf-warn{color:var(--dsw-alias-state-warn-primary)}
.nf-sec-title{font-size:13px;font-weight:600;margin:16px 0 8px}
.nf-hint{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin:4px 0 10px}
.nf-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.nf-pill{font-size:11.5px;padding:2px 8px;border-radius:10px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);white-space:nowrap}
.nf-proj{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;margin-bottom:8px;cursor:pointer;background:var(--dsw-alias-bg-layer-1)}
.nf-proj.on{border-color:var(--dsw-alias-brand-primary)}
.nf-gate{display:flex;gap:8px;align-items:flex-start;padding:4px 0;font-size:12px}
.nf-gate .st{min-width:40px;font-size:11px;font-weight:600;flex:0 0 auto}
.nf-gate .st.pass{color:var(--dsw-alias-state-success-primary)}
.nf-gate .st.fail{color:var(--dsw-alias-state-error-primary)}
.nf-gate .st.warn{color:var(--dsw-alias-state-warn-primary)}
.nf-code{font-family:Consolas,monospace;font-size:11.5px;background:var(--dsw-alias-bg-layer-2);padding:2px 6px;border-radius:5px;word-break:break-all}
.nf-loading{padding:30px;text-align:center;color:var(--dsw-alias-label-secondary)}
.nf-link{color:var(--dsw-alias-brand-primary);cursor:pointer;text-decoration:none}
`;

    const SEV_LABEL = { hard: '硬伤', warn: '建议修改', info: '观察' };
    const TABS = [
      ['project', '项目'],
      ['report', '报告'],
      ['approve', '审批'],
      ['kb', '知识库'],
      ['plot', '情节'],
      ['style', '风格'],
    ];

    function ForgeLogo() {
      return h(
        'svg',
        { className: 'nf-logo', viewBox: '0 0 64 64', 'aria-hidden': true },
        h('path', { d: 'M14 20c6-3 12-3 18 1v26c-6-4-12-4-18-1V20z', fill: 'none', stroke: 'currentColor', strokeWidth: 2.6, strokeLinejoin: 'round' }),
        h('path', { d: 'M50 20c-6-3-12-3-18 1v26c6-4 12-4 18-1V20z', fill: 'none', stroke: 'currentColor', strokeWidth: 2.6, strokeLinejoin: 'round' }),
        h('path', { d: 'M32 20v27', stroke: 'currentColor', strokeWidth: 2.2, strokeLinecap: 'round', opacity: 0.6 }),
        h('path', { d: 'M40 16c4 1 7 4 8 8-4 1-8-1-10-4', fill: 'currentColor', opacity: 0.9 }),
      );
    }

    function ForgeIcon(props) {
      const size = props && props.size ? props.size : 20;
      const active = props && props.active;
      return h(
        'svg',
        {
          width: size,
          height: size,
          viewBox: '0 0 64 64',
          fill: 'none',
          style: { color: active ? 'var(--dsw-alias-brand-primary)' : 'currentColor', display: 'block' },
          'aria-hidden': true,
        },
        h('path', { d: 'M14 20c6-3 12-3 18 1v26c-6-4-12-4-18-1V20z', stroke: 'currentColor', strokeWidth: 5, strokeLinejoin: 'round' }),
        h('path', { d: 'M50 20c-6-3-12-3-18 1v26c6-4 12-4 18-1V20z', stroke: 'currentColor', strokeWidth: 5, strokeLinejoin: 'round' }),
        h('path', { d: 'M32 21v26', stroke: 'currentColor', strokeWidth: 4.5, strokeLinecap: 'round', opacity: 0.65 }),
      );
    }

    async function api(action, payload) {
      const res = await fetch('/novel-forge/api', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        // action 放最后：payload 里同名的 action 是「子动作」（plot/style 用），
        // 不能被它覆盖掉外层分发用的 action，否则 dispatch 会收到 "list"/"import" 然后报未知动作。
        body: JSON.stringify({ ...(payload || {}), action }),
      });
      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }
      if (!res.ok || !data || data.ok === false) {
        throw new Error((data && data.error) || `请求失败（HTTP ${res.status}）`);
      }
      return data;
    }

    // 审批勾选 / 替换文本按「项目 + 轮次」存 localStorage：刷新页面或切页不丢。
    // 应用成功后清掉，避免带着上一轮勾选误操作；应用前 Host 也会把旧稿归档到 历史/。
    const APPROVAL_STORE = 'novel-forge:approval:';

    function approvalKey(projectName, round) {
      return APPROVAL_STORE + String(projectName || '') + ':' + String(round || '');
    }

    function loadApproval(projectName, round) {
      try {
        const raw = window.localStorage.getItem(approvalKey(projectName, round));
        if (!raw) return { selected: {}, replacements: {} };
        const data = JSON.parse(raw);
        return {
          selected: data && data.selected && typeof data.selected === 'object' ? data.selected : {},
          replacements: data && data.replacements && typeof data.replacements === 'object' ? data.replacements : {},
        };
      } catch {
        return { selected: {}, replacements: {} };
      }
    }

    function saveApproval(projectName, round, selected, replacements) {
      try {
        window.localStorage.setItem(
          approvalKey(projectName, round),
          JSON.stringify({ selected, replacements, saved_at: new Date().toISOString() }),
        );
      } catch {
        /* 隐私模式 / 配额满：存不进去就不是致命问题 */
      }
    }

    function clearApproval(projectName, round) {
      try {
        window.localStorage.removeItem(approvalKey(projectName, round));
      } catch {
        /* ignore */
      }
    }

    function StatCard(props) {
      return h(
        'div',
        { className: 'nf-card', style: { marginBottom: 0 } },
        h('div', { className: 'nf-stat' }, props.value),
        h('div', { className: 'nf-stat-label' }, props.label),
      );
    }

    function ScorePanel(props) {
      const score = props.score;
      if (!score) return h('div', { className: 'nf-muted' }, '还没有评分，先扫描一次。');
      return h(
        'div',
        { className: 'nf-card' },
        h('div', { className: 'nf-row', style: { justifyContent: 'space-between' } },
          h('div', null,
            h('h3', null, '编辑健康度'),
            h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 10 } },
              h('span', { className: 'nf-stat', style: { fontSize: 26 } }, score.total),
              h('span', { className: 'nf-pill' }, score.grade),
              h('span', { className: 'nf-muted', style: { fontSize: 12 } }, score.summary || ''),
            ),
          ),
          h('div', { className: 'nf-muted', style: { fontSize: 11.5, maxWidth: 280, textAlign: 'right' } }, '评分透明可解释：硬门禁 / 设定一致性 / 重复冗余 / AI 腔 / 节奏与钩子 / 文风保真'),
        ),
        h('div', { style: { marginTop: 10 } },
          (score.dimensions || []).map((d) => {
            // 未测维度（score=null / measured=false）不能画成 2% 的条，否则看着像 0 分。
            const measured = d.measured !== false && d.score != null;
            return h('div', { className: 'nf-dim', key: d.id, style: measured ? undefined : { opacity: 0.55 } },
              h('div', { className: 'nf-dim-name' }, d.name),
              h('div', { className: 'nf-bar' },
                measured
                  ? h('i', { style: { width: `${Math.max(2, d.score)}%` } })
                  : h('i', { style: { width: '0%' } })),
              h('div', { className: 'nf-score' }, measured ? d.score : '未测'),
              h('div', { className: 'nf-muted', style: { fontSize: 11, minWidth: 130 } }, d.detail),
            );
          }),
        ),
        score.weak_hooks && score.weak_hooks.length
          ? h('div', { style: { marginTop: 10 } },
              h('div', { className: 'nf-sec-title', style: { marginTop: 4 } }, '章末钩子偏弱'),
              h('div', { className: 'nf-row' },
                score.weak_hooks.map((w) =>
                  h('span', { className: 'nf-pill', key: w.index }, `第${w.index}章 · ${w.score} 分`),
                ),
              ),
            )
          : null,
      );
    }

    function GateList(props) {
      const gates = props.gates || [];
      if (!gates.length) return h('div', { className: 'nf-muted' }, '还没有体检结果。');
      return h(
        'div',
        null,
        gates.map((g) =>
          h('div', { className: 'nf-gate', key: g.id },
            h('span', { className: `st ${g.status}` }, g.status === 'pass' ? '通过' : g.status === 'fail' ? '未过' : '提醒'),
            h('span', null, h('b', null, g.name + '：'), g.detail),
          ),
        ),
      );
    }

    function FindingCard(props) {
      const f = props.finding;
      const selected = props.selected;
      const replacement = props.replacement || '';
      return h(
        'div',
        { className: 'nf-find' },
        h('div', { className: 'nf-find-h' },
          h('label', { className: 'nf-check' },
            h('input', {
              type: 'checkbox',
              checked: selected,
              onChange: (event) => props.onToggle(f.id, event.target.checked),
            }),
            '批准',
          ),
          h('span', { className: 'nf-loc' }, `第${f.chapter}章 · 第${f.para_display}段`),
          h('span', { className: `nf-badge ${f.severity}` }, SEV_LABEL[f.severity] || f.severity),
          h('span', { className: 'nf-badge' }, f.category),
          h('span', { className: 'nf-muted', style: { fontSize: 11 } }, f.id),
        ),
        h('div', { className: 'nf-q' }, f.quote),
        h('div', { className: 'nf-why' }, h('b', null, '为什么：'), f.why),
        h('div', { className: 'nf-why' }, h('b', null, '建议：'), f.suggestion),
        selected
          ? h('div', { style: { marginTop: 8 } },
              h('div', { className: 'nf-hint', style: { margin: '0 0 4px' } },
                f.action === 'delete'
                  ? '批准后将整段删除；如需改写请填写替换文本。'
                  : '替换文本 = 整段改写；留空表示只记录、不改文本。',
              ),
              h('textarea', {
                className: 'nf-textarea',
                value: replacement,
                placeholder: f.action === 'delete' ? '（默认：删除整段）' : '例如：删掉这句，只留一个动作。',
                onChange: (event) => props.onReplacement(f.id, event.target.value),
              }),
            )
          : null,
      );
    }

    function ProjectTab(props) {
      const { projects, project, report, health, onOpen, onScan, busy } = props;
      return h(
        'div',
        null,
        h('div', { className: 'nf-sec-title', style: { marginTop: 0 } }, '书项目'),
        h('div', { className: 'nf-hint' }, `数据目录：${health ? health.dataRoot : '…'}　引擎：Python ${health ? '已就绪' : '…'}`),
        props.healthError ? h('div', { className: 'nf-err' }, '健康检查失败：' + props.healthError) : null,
        (projects || []).map((p) =>
          h('div', {
            key: p.name,
            className: `nf-proj ${project && project.name === p.name ? 'on' : ''}`,
            onClick: () => onOpen(p.name),
          },
            h('div', null,
              h('div', { style: { fontWeight: 600 } }, p.title),
              h('div', { className: 'nf-muted', style: { fontSize: 11.5 } },
                `${p.stats ? p.stats.chapters : '?'} 章 / ${p.stats ? p.stats.total_paragraphs : '?'} 段 / ${p.stats ? p.stats.cjk_with_headings : '?'} 字` +
                `　主稿：${p.mainDraft || '?'}　轮次：${p.rounds || 0}`,
              ),
            ),
            h('div', { className: 'nf-row' },
              p.score != null ? h('span', { className: 'nf-pill' }, `${p.score} ${p.grade || ''}`) : null,
              p.lastScanAt ? h('span', { className: 'nf-muted', style: { fontSize: 11 } }, p.lastScanAt.slice(0, 10)) : null,
            ),
          ),
        ),
        project
          ? h('div', null,
              h('div', { className: 'nf-sec-title' }, `当前项目：${project.config.title}`),
              h('div', { className: 'nf-grid', style: { gridTemplateColumns: 'repeat(4,1fr)' } },
                h(StatCard, { value: report ? report.stats.chapters : '—', label: '章' }),
                h(StatCard, { value: report ? report.stats.total_paragraphs : '—', label: '段（含标题）' }),
                h(StatCard, { value: report ? report.stats.cjk_with_headings : '—', label: '字（含标题）' }),
                h(StatCard, { value: report ? report.findings.length : '—', label: '候选项' }),
              ),
              h('div', { className: 'nf-card', style: { marginTop: 12 } },
                h('h3', null, '下一步'),
                h('div', { className: 'nf-row' },
                  h('button', { className: 'nf-btn primary', disabled: !!busy, onClick: onScan },
                    busy === 'scan' ? '扫描中…' : '扫描主稿，生成第 N 轮改动清单'),
                  report
                    ? h('button', { className: 'nf-btn', onClick: () => props.onTab('report') }, '查看报告')
                    : null,
                ),
                h('div', { className: 'nf-hint', style: { marginBottom: 0, marginTop: 8 } },
                  '扫描只读主稿、不改稿；所有改动都要在「报告 / 审批」里勾选后才应用。',
                ),
              ),
              h('div', { className: 'nf-card' },
                h('h3', null, '轮次'),
                project.rounds && project.rounds.length
                  ? h('table', { className: 'nf-table' },
                      h('thead', null, h('tr', null, h('th', null, '轮次'), h('th', null, '扫描'), h('th', null, '已应用'), h('th', null, '产出'))),
                      h('tbody', null,
                        project.rounds.map((r) =>
                          h('tr', { key: r.name },
                            h('td', null, r.name),
                            h('td', null, r.hasScan ? '✓' : '—'),
                            h('td', null, r.hasApply ? '✓' : '—'),
                            h('td', null, r.draft ? '已生成新稿' : '—'),
                          ),
                        ),
                      ),
                    )
                  : h('div', { className: 'nf-muted' }, '还没有轮次，点上面的扫描按钮。'),
              ),
              h('div', { className: 'nf-card' },
                h('h3', null, '当前主稿'),
                h('div', { className: 'nf-code' }, project.config.main_draft),
                h('div', { className: 'nf-hint', style: { marginBottom: 0, marginTop: 6 } },
                  '扫描永远只读；应用会生成 rounds/第N轮/稿子_第N轮.docx，不会覆盖主稿。',
                ),
              ),
            )
          : null,
      );
    }

    function AuditPanel(props) {
      const audit = props.audit;
      if (!audit) return null;
      const [open, setOpen] = useState(true);
      const metrics = audit.metrics || [];
      return h(
        'div',
        { className: 'nf-card' },
        h('div', { className: 'nf-row', style: { justifyContent: 'space-between' } },
          h('h3', { style: { margin: 0 } }, 'AI 味审计（v4 指标 · 编辑模式：只报告）'),
          h('button', { className: 'nf-btn', onClick: () => setOpen((value) => !value) }, open ? '收起' : '展开'),
        ),
        h('div', { className: 'nf-hint' }, (audit.policy && audit.policy.summary) || '只报告，不硬卡。'),
        open
          ? h('div', null,
              h('table', { className: 'nf-table', style: { fontSize: 11.5 } },
                h('thead', null, h('tr', null,
                  h('th', null, '指标'),
                  h('th', null, '全书值'),
                  h('th', null, '默认区 绿/黄/红'),
                  h('th', null, '本书基线'),
                  h('th', null, '偏差'),
                  h('th', null, '处理'),
                )),
                h('tbody', null,
                  metrics.map((m) =>
                    h('tr', { key: m.id },
                      h('td', null, `${m.id} ${m.name}`),
                      h('td', null, m.enabled === false || m.book_value == null ? '—' : m.book_value),
                      h('td', null, m.default_zones ? `${m.default_zones.green} / ${m.default_zones.yellow} / ${m.default_zones.red}` : '—'),
                      h('td', null, m.baseline_value == null ? '—' : m.baseline_value),
                      h('td', null, m.deviation_pct == null ? '—' : `${m.deviation_pct > 0 ? '+' : ''}${m.deviation_pct}%`),
                      h('td', null, m.enabled === false ? '未启用' : (m.policy === 'warn' ? '告警' : '只报告')),
                    ),
                  ),
                ),
              ),
              (audit.notes || []).length
                ? h('div', { style: { marginTop: 8 } },
                    (audit.notes || []).map((note, index) =>
                      h('div', { key: index, className: 'nf-hint', style: { margin: '3px 0' } }, '· ' + note),
                    ),
                  )
                : null,
            )
          : null,
      );
    }

    function ReportTab(props) {
      const { report, selected, onToggle, onReplacement, replacements, rounds, onRound } = props;
      if (!report) {
        return h('div', { className: 'nf-empty' }, '还没有扫描结果。先回「项目」页点扫描，或去聊天里让 AI 调用 novel_scan。');
      }
      const allFindings = report.findings || [];
      const findings = allFindings.filter((f) => !(f.meta && f.meta.audit));
      const auditFindings = allFindings.length - findings.length;
      const [severity, setSeverity] = useState('all');
      const [category, setCategory] = useState('all');
      const categories = Array.from(new Set(findings.map((f) => f.category)));
      const filtered = findings.filter((f) => (severity === 'all' || f.severity === severity) && (category === 'all' || f.category === category));
      const scanRounds = (rounds || []).filter((item) => item.hasScan);
      return h(
        'div',
        null,
        scanRounds.length > 1 && onRound
          ? h('div', { className: 'nf-row', style: { marginBottom: 10 } },
              h('span', { className: 'nf-muted', style: { fontSize: 11.5 } }, '查看轮次'),
              h('select', {
                value: report.round,
                onChange: (event) => onRound(event.target.value),
                style: {
                  padding: '5px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)',
                  background: 'var(--dsw-alias-bg-layer-1)', color: 'var(--dsw-alias-label-primary)', fontSize: 12,
                },
              },
                scanRounds.map((item) =>
                  h('option', { key: item.name, value: item.name }, `${item.name}${item.hasApply ? ' · 已应用' : ''}`),
                ),
              ),
              h('span', { className: 'nf-hint', style: { margin: 0 } }, '历史轮次只读；勾选应用会写到该轮目录。'),
            )
          : null,
        h(ScorePanel, { score: report.score }),
        h(AuditPanel, { audit: report.audit }),
        h('div', { className: 'nf-sec-title' }, `候选项（${findings.length}）` + (auditFindings ? `　AI 味审计告警 ${auditFindings} 条（见上）` : '')),
        h('div', { className: 'nf-hint' },
          '勾选「批准」才会进入审批；文本改法可留空（只记录）或填整段替换。所有候选项都来自规则扫描，可能有观察项，请按你的判断取舍。',
        ),
        h('div', { className: 'nf-row', style: { marginBottom: 10 } },
          ['all', 'hard', 'warn', 'info'].map((key) =>
            h('button', {
              key,
              className: `nf-tab ${severity === key ? 'on' : ''}`,
              style: { border: '1px solid var(--dsw-alias-border-l1)' },
              onClick: () => setSeverity(key),
            }, key === 'all' ? `全部 ${findings.length}` : `${SEV_LABEL[key]} ${findings.filter((f) => f.severity === key).length}`),
          ),
          h('select', {
            value: category,
            onChange: (event) => setCategory(event.target.value),
            style: {
              marginLeft: 6, padding: '5px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)',
              background: 'var(--dsw-alias-bg-layer-1)', color: 'var(--dsw-alias-label-primary)', fontSize: 12,
            },
          },
            h('option', { value: 'all' }, '全部分类'),
            categories.map((c) => h('option', { key: c, value: c }, c)),
          ),
        ),
        filtered.length
          ? filtered.map((f) =>
              h(FindingCard, {
                key: f.id,
                finding: f,
                selected: !!selected[f.id],
                replacement: (replacements || {})[f.id] || '',
                onToggle,
                onReplacement,
              }),
            )
          : h('div', { className: 'nf-empty' }, '这个筛选下没有候选项。'),
        h('div', { className: 'nf-sec-title' }, '章级体检'),
        h('table', { className: 'nf-table' },
          h('thead', null, h('tr', null,
            h('th', null, '章'), h('th', null, '标题'), h('th', null, '字'), h('th', null, '段'),
            h('th', null, '对白比'), h('th', null, '钩子'), h('th', null, '问题'),
          )),
          h('tbody', null,
            (report.chapters || []).map((c) =>
              h('tr', { key: c.index },
                h('td', null, c.index),
                h('td', null, c.title.replace(/^第\d+章\s*/, '')),
                h('td', null, c.cjk),
                h('td', null, c.paras),
                h('td', null, `${Math.round((c.dialogue_ratio || 0) * 100)}%`),
                h('td', { className: c.hook && c.hook.score < 45 ? 'nf-warn' : '' }, c.hook ? c.hook.score : '—'),
                h('td', null, `${c.severity_counts.hard}硬 / ${c.severity_counts.warn}议 / ${c.severity_counts.info}观`),
              ),
            ),
          ),
        ),
      );
    }

    function ApproveTab(props) {
      const { report, selected, replacements, applyResult, busy, onApply, onClear, onReplacement, onToggle, markdown } = props;
      const findings = report ? (report.findings || []).filter((f) => selected[f.id]) : [];
      return h(
        'div',
        null,
        h('div', { className: 'nf-sec-title', style: { marginTop: 0 } }, `已批准（${findings.length}）`),
        h('div', { className: 'nf-hint' }, '应用会以主稿为基准，按当前批准集合重新生成新稿，并自动跑门禁体检。'),
        findings.length
          ? findings.map((f) =>
              h('div', { className: 'nf-find', key: f.id },
                h('div', { className: 'nf-find-h' },
                  h('span', { className: 'nf-loc' }, `第${f.chapter}章 · 第${f.para_display}段`),
                  h('span', { className: `nf-badge ${f.severity}` }, SEV_LABEL[f.severity]),
                  h('span', { className: 'nf-badge' }, f.category),
                  h('label', { className: 'nf-check', style: { marginLeft: 'auto' } },
                    h('input', { type: 'checkbox', checked: true, onChange: () => onToggle(f.id, false) }),
                    '移除',
                  ),
                ),
                h('div', { className: 'nf-q' }, f.quote),
                h('textarea', {
                  className: 'nf-textarea',
                  value: (replacements || {})[f.id] || '',
                  placeholder: f.action === 'delete' ? '（默认：删除整段）' : '整段替换文本（留空=只记录）',
                  onChange: (event) => onReplacement(f.id, event.target.value),
                }),
              ),
            )
          : h('div', { className: 'nf-empty' }, '还没有批准任何候选项。去「报告」页勾选。'),
        h('div', { className: 'nf-row', style: { marginTop: 10 } },
          h('button', { className: 'nf-btn primary', disabled: !!busy || !findings.length, onClick: onApply },
            busy === 'apply' ? '应用中…' : '应用已批准，生成新稿'),
          h('button', { className: 'nf-btn', disabled: !!busy || !findings.length, onClick: onClear }, '清空勾选'),
          report ? h('span', { className: 'nf-muted', style: { fontSize: 11.5 } }, `轮次：${report.round}`) : null,
        ),
        applyResult
          ? h('div', { className: 'nf-card', style: { marginTop: 12 } },
              h('h3', null, '应用结果'),
              h('div', { className: 'nf-row' },
                h('span', { className: applyResult.verify && applyResult.verify.pass ? 'nf-ok' : 'nf-err' },
                  applyResult.verify && applyResult.verify.pass ? `门禁通过（${applyResult.applied} 条改动，${applyResult.delta_cjk >= 0 ? '+' : ''}${applyResult.delta_cjk} 字）` : '门禁未通过'),
              ),
              h('div', { className: 'nf-hint', style: { marginTop: 6 } },
                '新稿：', h('span', { className: 'nf-code' }, applyResult.output),
              ),
              applyResult.reapply && applyResult.reapply.archived && applyResult.reapply.archived.length
                ? h('div', { className: 'nf-hint', style: { marginTop: 6 } },
                    '同轮重复应用：上一版稿子/记录已归档到 ',
                    h('span', { className: 'nf-code' }, applyResult.reapply.archived[0]),
                  )
                : null,
              h(GateList, { gates: applyResult.verify ? applyResult.verify.gates : [] }),
            )
          : null,
        markdown
          ? h('div', { className: 'nf-hint', style: { marginTop: 10 } },
              '改动清单：', h('span', { className: 'nf-code' }, markdown),
            )
          : null,
      );
    }

    // 默认章号不再写死 27：从项目真实数据推导（最新扫描报告的 stats.chapters），
    // 拿不到就回退 1，再 clamp 到 [1, 章节数]，换书 / 加章都不会去查不存在的章。
    function projectChapters(project) {
      const stats = project && project.report && project.report.stats;
      const total = Number(stats && stats.chapters);
      return Number.isFinite(total) && total >= 1 ? Math.floor(total) : 1;
    }

    function clampChapter(value, total) {
      const n = Math.floor(Number(value));
      if (!Number.isFinite(n)) return 1;
      return Math.min(total, Math.max(1, n));
    }

    function KbTab(props) {
      const project = props.project;
      const [data, setData] = useState(null);
      const [query, setQuery] = useState('');
      const [results, setResults] = useState(null);
      // null = 自动跟随项目章节数，用户改过才锁成具体数字。
      const [chapter, setChapter] = useState(null);
      const totalChapters = projectChapters(project);
      const chapterNo = chapter == null ? totalChapters : clampChapter(chapter, totalChapters);
      const [context, setContext] = useState(null);
      const [busy, setBusy] = useState('');
      const [error, setError] = useState('');

      const load = useCallback(async () => {
        if (!project) return;
        setBusy('load');
        setError('');
        try {
          const next = await api('kb_list', { project: project.name });
          setData(next);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project]);

      useEffect(() => {
        if (project) load();
      }, [project, load]);

      const sync = async () => {
        if (!project) return;
        setBusy('sync');
        setError('');
        try {
          await api('kb_sync', { project: project.name });
          await load();
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      };

      const search = async () => {
        if (!project || !query.trim()) return;
        setBusy('search');
        setError('');
        try {
          const next = await api('kb_search', { project: project.name, query: query.trim(), limit: 12 });
          setResults(next.results || []);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      };

      const loadContext = async () => {
        if (!project) return;
        setBusy('context');
        setError('');
        try {
          const next = await api('kb_context', { project: project.name, chapter: chapterNo, maxChars: 4000 });
          setContext(next);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      };

      if (!project) return h('div', { className: 'nf-empty' }, '先选一个书项目。');
      const authority = { outline: '大纲', worldview: '知识库', extra: '番外', book: '正文' };
      return h(
        'div',
        null,
        h('div', { className: 'nf-card' },
          h('div', { className: 'nf-row', style: { justifyContent: 'space-between' } },
            h('h3', { style: { margin: 0 } }, '知识库设定集'),
            h('div', { className: 'nf-row' },
              h('span', { className: 'nf-pill' }, data ? `${(data.cards || []).length} 张卡` : '未同步'),
              h('button', { className: 'nf-btn', disabled: !!busy, onClick: sync }, busy === 'sync' ? '同步中…' : '重新同步'),
            ),
          ),
          error ? h('div', { className: 'nf-err' }, error) : null,
          !data
            ? h('div', { className: 'nf-hint' }, '还没有知识库索引。点「重新同步」解析 kb/sources 下的 大纲 / 知识库 / 番外。')
            : h('div', null,
                h('div', { className: 'nf-hint' },
                  '来源：' + (data.sources || []).map((s) => `${s.file}（${authority[s.authority] || s.authority}，${s.cards} 卡${s.spoiler ? '，剧透' : ''}）`).join('　'),
                ),
                h('table', { className: 'nf-table' },
                  h('thead', null, h('tr', null, h('th', null, '来源'), h('th', null, '权威'), h('th', null, '卡片'), h('th', null, '剧透'))),
                  h('tbody', null,
                    (data.sources || []).map((s) =>
                      h('tr', { key: s.file },
                        h('td', null, s.file),
                        h('td', null, authority[s.authority] || s.authority),
                        h('td', null, s.cards),
                        h('td', null, s.spoiler ? '是（默认不进正文上下文）' : '否'),
                      ),
                    ),
                  ),
                ),
                h('div', { className: 'nf-hint', style: { marginTop: 8 } },
                  (data.policy && data.policy.conflict_rule) || '正文优先；六类核心以大纲为准。',
                ),
              ),
        ),
        h('div', { className: 'nf-card' },
          h('h3', null, '检索设定'),
          h('div', { className: 'nf-row' },
            h('input', {
              value: query,
              placeholder: '如：力量体系 / 人物身份 / 引路灯',
              onChange: (event) => setQuery(event.target.value),
              onKeyDown: (event) => { if (event.key === 'Enter') search(); },
              style: {
                flex: 1, minWidth: 240, padding: '7px 10px', borderRadius: 7,
                border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)',
                color: 'var(--dsw-alias-label-primary)', fontSize: 12, fontFamily: 'inherit',
              },
            }),
            h('button', { className: 'nf-btn primary', disabled: !!busy, onClick: search }, busy === 'search' ? '检索中…' : '检索'),
          ),
          results
            ? (results.length
                ? results.map((item) =>
                    h('div', { key: item.id, className: 'nf-find', style: { marginTop: 10 } },
                      h('div', { className: 'nf-find-h' },
                        h('span', { className: 'nf-loc' }, item.title),
                        h('span', { className: 'nf-badge' }, authority[item.authority] || item.authority),
                        item.spoiler ? h('span', { className: 'nf-badge warn' }, '番外·剧透') : null,
                        h('span', { className: 'nf-muted', style: { fontSize: 11 } }, item.source),
                      ),
                      h('div', { className: 'nf-q' }, item.snippet),
                      item.path ? h('div', { className: 'nf-hint', style: { margin: 0 } }, item.path) : null,
                    ),
                  )
                : h('div', { className: 'nf-empty', style: { marginTop: 10 } }, '没有命中。'))
            : null,
        ),
        h('div', { className: 'nf-card' },
          h('h3', null, '章节上下文包'),
          h('div', { className: 'nf-hint' }, '按章内实体召回相关设定卡，给续写/审稿用；番外默认不进。'),
          h('div', { className: 'nf-row' },
            h('span', { className: 'nf-muted' }, '第'),
            h('input', {
              type: 'number', min: 1, max: totalChapters, value: chapterNo,
              onChange: (event) => setChapter(event.target.value),
              style: {
                width: 72, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)',
                background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', fontSize: 12,
              },
            }),
            h('span', { className: 'nf-muted' }, '章'),
            h('button', { className: 'nf-btn', disabled: !!busy, onClick: loadContext }, busy === 'context' ? '生成中…' : '生成上下文包'),
          ),
          context
            ? h('div', { style: { marginTop: 8 } },
                h('div', { className: 'nf-hint' }, `关键词：${(context.keywords || []).join('、')}　卡 ${(context.cards || []).length} 张 / ${context.chars} 字`),
                (context.cards || []).slice(0, 6).map((card) =>
                  h('div', { key: card.id, className: 'nf-find' },
                    h('div', { className: 'nf-find-h' },
                      h('span', { className: 'nf-loc' }, card.title),
                      h('span', { className: 'nf-badge' }, authority[card.authority] || card.authority),
                      card.spoiler ? h('span', { className: 'nf-badge warn' }, '剧透') : null,
                      h('span', { className: 'nf-muted', style: { fontSize: 11 } }, `匹配：${(card.matched_keywords || []).join('、')}`),
                    ),
                    h('div', { className: 'nf-q' }, (card.content || '').slice(0, 220) + ((card.content || '').length > 220 ? '…' : '')),
                  ),
                ),
              )
            : null,
        ),
      );
    }

    function PlotTab(props) {
      const project = props.project;
      const [data, setData] = useState(null);
      const [validation, setValidation] = useState(null);
      const [busy, setBusy] = useState('');
      const [error, setError] = useState('');

      const load = useCallback(async () => {
        if (!project) return;
        setBusy('load');
        setError('');
        try {
          setData(await api('plot', { project: project.name, action: 'list' }));
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project]);

      useEffect(() => {
        if (project) load();
      }, [project, load]);

      const validate = async (chapterKey) => {
        if (!project) return;
        setBusy('validate');
        setError('');
        try {
          setValidation(await api('plot', { project: project.name, action: 'validate', chapter_key: chapterKey }));
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      };

      if (!project) return h('div', { className: 'nf-empty' }, '先选一个书项目。');
      const plots = (data && data.plots) || [];
      return h(
        'div',
        null,
        h('div', { className: 'nf-card' },
          h('div', { className: 'nf-row', style: { justifyContent: 'space-between' } },
            h('h3', { style: { margin: 0 } }, '情节拼接 · 节拍卡'),
            h('div', { className: 'nf-row' },
              h('span', { className: 'nf-pill' }, `${plots.length} 章节拍`),
              h('button', { className: 'nf-btn', disabled: !!busy, onClick: load }, '刷新'),
            ),
          ),
          error ? h('div', { className: 'nf-err' }, error) : null,
          h('div', { className: 'nf-hint' },
            '细纲来源在 plot/sources；import 解析后得到节拍卡。用 chat 工具 novel_plot(action=template) 拿拆分 prompt，submit 落盘；这里只做查看/校验。',
          ),
          plots.length
            ? h('table', { className: 'nf-table' },
                h('thead', null, h('tr', null,
                  h('th', null, '章键'), h('th', null, '标题'), h('th', null, '拍数'),
                  h('th', null, '目标字数'), h('th', null, '来源'), h('th', null, '操作'),
                )),
                h('tbody', null,
                  plots.map((plot) =>
                    h('tr', { key: plot.chapter_key },
                      h('td', null, plot.chapter_key),
                      h('td', null, plot.title || '—'),
                      h('td', null, plot.beats),
                      h('td', null, plot.target_chars || '—'),
                      h('td', null, plot.source || '—'),
                      h('td', null,
                        h('button', { className: 'nf-btn', disabled: !!busy, onClick: () => validate(plot.chapter_key) }, '校验'),
                      ),
                    ),
                  ),
                ),
              )
            : h('div', { className: 'nf-empty' }, '还没有节拍卡。让 AI 用 novel_plot 导入 第28章_细纲.md，或按 template 拆新章。'),
        ),
        validation
          ? h('div', { className: 'nf-card' },
              h('h3', null, `校验：${validation.chapter_key}（${validation.pass ? '通过' : '有硬问题'}）`),
              h('div', { className: 'nf-hint' },
                `${validation.beats} 拍 / 目标 ${validation.target_chars_total} 字 / 预估 ${(validation.estimated_chars || []).join('–')} / 章末钩子 ${validation.hook.score} 分`,
              ),
              (validation.findings || []).length
                ? validation.findings.map((finding, index) =>
                    h('div', { key: index, className: 'nf-gate' },
                      h('span', { className: `st ${finding.severity === 'fail' ? 'fail' : 'warn'}` }, finding.severity === 'fail' ? '未过' : '提醒'),
                      h('span', null, `${finding.beat || ''} ${finding.message}`),
                    ),
                  )
                : h('div', { className: 'nf-ok' }, '没有发现问题。'),
            )
          : null,
      );
    }

    function StyleTab(props) {
      const project = props.project;
      const [data, setData] = useState(null);
      const [name, setName] = useState('');
      // 同上：默认章号跟随项目章节数，不再写死 27。
      const [chapter, setChapter] = useState(null);
      const totalChapters = projectChapters(project);
      const chapterNo = chapter == null ? totalChapters : clampChapter(chapter, totalChapters);
      const [para, setPara] = useState(0);
      const [result, setResult] = useState(null);
      const [busy, setBusy] = useState('');
      const [error, setError] = useState('');

      const load = useCallback(async () => {
        if (!project) return;
        setBusy('load');
        setError('');
        try {
          const next = await api('style', { project: project.name, action: 'list' });
          setData(next);
          if (!name && next.styles && next.styles.length) setName(next.styles[0].name);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project, name]);

      useEffect(() => {
        if (project) load();
      }, [project, load]);

      const check = async () => {
        if (!project || !name) return;
        setBusy('check');
        setError('');
        try {
          const next = await api('style', {
            project: project.name, action: 'check', name,
            chapter: chapterNo, para: Number(para) || 0,
          });
          setResult(next);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      };

      if (!project) return h('div', { className: 'nf-empty' }, '先选一个书项目。');
      const styles = (data && data.styles) || [];
      return h(
        'div',
        null,
        h('div', { className: 'nf-card' },
          h('div', { className: 'nf-row', style: { justifyContent: 'space-between' } },
            h('h3', { style: { margin: 0 } }, '文风调性 · 粘性'),
            h('button', { className: 'nf-btn', disabled: !!busy, onClick: load }, '刷新'),
          ),
          error ? h('div', { className: 'nf-err' }, error) : null,
          h('div', { className: 'nf-hint' },
            '粘性 = 文本与风格样本的贴合度（0–100）；样本互测一致性是它的上限。只做检测，不改稿；改写走 A.6。',
          ),
          styles.length
            ? h('table', { className: 'nf-table' },
                h('thead', null, h('tr', null,
                  h('th', null, '风格'), h('th', null, '样本'), h('th', null, '学到的段落'), h('th', null, '样本互测'),
                )),
                h('tbody', null,
                  styles.map((style) =>
                    h('tr', { key: style.name },
                      h('td', null, style.name),
                      h('td', null, style.samples),
                      h('td', null, style.paragraphs),
                      h('td', null, style.sample_consistency == null ? '—' : style.sample_consistency),
                    ),
                  ),
                ),
              )
            : h('div', { className: 'nf-empty' }, '还没有风格档案。让 AI 用 novel_style(action=learn) 从样本学一个。'),
        ),
        h('div', { className: 'nf-card' },
          h('h3', null, '检查某一段'),
          h('div', { className: 'nf-row' },
            h('select', {
              value: name, onChange: (event) => setName(event.target.value),
              style: { padding: '6px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-layer-1)', color: 'var(--dsw-alias-label-primary)', fontSize: 12 },
            }, styles.map((style) => h('option', { key: style.name, value: style.name }, style.name))),
            h('span', { className: 'nf-muted' }, '第'),
            h('input', { type: 'number', min: 1, max: totalChapters, value: chapterNo, onChange: (event) => setChapter(event.target.value), style: { width: 66, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', fontSize: 12 } }),
            h('span', { className: 'nf-muted' }, '章'),
            h('input', { type: 'number', min: 0, value: para, onChange: (event) => setPara(event.target.value), style: { width: 66, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', fontSize: 12 } }),
            h('span', { className: 'nf-muted' }, '段（0 起）'),
            h('button', { className: 'nf-btn primary', disabled: !!busy || !name, onClick: check }, busy === 'check' ? '计算中…' : '测粘性'),
          ),
          result
            ? h('div', { style: { marginTop: 10 } },
                h('div', { className: 'nf-row' },
                  h('span', { className: 'nf-stat', style: { fontSize: 22 } }, result.adhesion),
                  h('span', { className: 'nf-pill' }, result.verdict),
                  h('span', { className: 'nf-muted', style: { fontSize: 12 } }, `目标：${result.style} · ${result.chars} 字 · 样本上限 ${result.sample_consistency ?? '—'}`),
                ),
                (result.alternatives || []).length
                  ? h('div', { className: 'nf-hint' }, '其他风格：' + result.alternatives.map((item) => `${item.style} ${item.adhesion}`).join('　'))
                  : null,
                h('div', { className: 'nf-hint', style: { marginTop: 8 } }, '最弱特征：'),
                (result.weakest || []).map((item) =>
                  h('div', { key: item.key, className: 'nf-hint', style: { margin: '2px 0' } },
                    `${item.label}：目标 ${item.value} / 样本均值 ${item.mean}（z=${item.z}）`,
                  ),
                ),
              )
            : null,
        ),
      );
    }

    function PlaceholderTab(props) {
      return h(
        'div',
        { className: 'nf-card' },
        h('h3', null, props.title),
        h('div', { className: 'nf-muted', style: { fontSize: 12, marginBottom: 8 } }, 'P1 建设中，以下是已确定的设计。'),
        (props.items || []).map((item) => h('div', { key: item, style: { margin: '5px 0' } }, '· ' + item)),
      );
    }

    class Boundary extends React.Component {
      constructor(props) {
        super(props);
        this.state = { error: null };
      }
      static getDerivedStateFromError(error) {
        return { error };
      }
      render() {
        if (this.state.error) {
          return h('div', { className: 'nf-root' },
            h('div', { className: 'nf-body' },
              h('div', { className: 'nf-err' }, '小说工坊面板出错：' + String(this.state.error && this.state.error.message ? this.state.error.message : this.state.error)),
            ),
          );
        }
        return this.props.children;
      }
    }

    function App() {
      const [projects, setProjects] = useState(null);
      const [project, setProject] = useState(null);
      const [report, setReport] = useState(null);
      const [markdown, setMarkdown] = useState(null);
      const [health, setHealth] = useState(null);
      const [tab, setTab] = useState('project');
      const [selected, setSelected] = useState({});
      const [replacements, setReplacements] = useState({});
      const [busy, setBusy] = useState('');
      const [error, setError] = useState('');
      const [applyResult, setApplyResult] = useState(null);

      const [healthError, setHealthError] = useState('');

      const loadHealth = useCallback(async () => {
        try {
          const res = await fetch('/novel-forge/health');
          const data = await res.json();
          setHealthError(data && data.ok ? '' : (data && data.error) || '健康检查未通过');
          if (data && data.ok) setHealth(data);
        } catch (err) {
          // 原来这里是空 catch：健康接口挂了界面上一点痕迹都没有，现在落成可展示的状态。
          setHealthError((err && err.message) || '健康检查失败');
        }
      }, []);

      const openProject = useCallback(async (name) => {
        setBusy('project');
        setError('');
        try {
          const data = await api('project', { project: name });
          setProject(data.project);
          setReport(data.project.report || null);
          setMarkdown(data.project.markdown || null);
          // 勾选/替换文本按项目+轮次从 localStorage 恢复，刷新不丢。
          const restored = loadApproval(name, data.project.report ? data.project.report.round : null);
          setSelected(restored.selected);
          setReplacements(restored.replacements);
          setApplyResult(null);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, []);

      const bootstrap = useCallback(async () => {
        setBusy('load');
        setError('');
        try {
          loadHealth();
          const data = await api('projects');
          const list = data.projects || [];
          setProjects(list);
          if (list.length) await openProject(list[0].name);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [loadHealth, openProject]);

      useEffect(() => {
        bootstrap();
      }, [bootstrap]);

      const scan = useCallback(async () => {
        if (!project) return;
        setBusy('scan');
        setError('');
        try {
          const data = await api('scan', { project: project.name });
          if (data.ok === false) throw new Error(data.error || '扫描失败');
          setReport(data);
          const detail = await api('project', { project: project.name });
          setProject(detail.project);
          setMarkdown(detail.project.markdown || null);
          setSelected({});
          setReplacements({});
          setApplyResult(null);
          clearApproval(project.name, data.round);
          setTab('report');
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project]);

      const toggle = useCallback((id, next) => {
        setSelected((prev) => {
          const copy = { ...prev };
          if (next) copy[id] = true;
          else delete copy[id];
          return copy;
        });
      }, []);

      const setReplacement = useCallback((id, text) => {
        setReplacements((prev) => ({ ...prev, [id]: text }));
      }, []);

      // 勾选 / 替换文本一变就落 localStorage（按「项目+轮次」隔离），刷新页面不丢。
      useEffect(() => {
        if (!project || !report) return;
        saveApproval(project.name, report.round, selected, replacements);
      }, [project, report, selected, replacements]);

      const openRound = useCallback(async (roundName) => {
        if (!project || !roundName) return;
        setBusy('report');
        setError('');
        try {
          const data = await api('report', { project: project.name, round: roundName });
          setReport(data.report ? { ...data.report, round: data.round } : null);
          setMarkdown(data.markdown || null);
          setApplyResult(null);
          const restored = loadApproval(project.name, data.round);
          setSelected(restored.selected);
          setReplacements(restored.replacements);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project]);

      const clearAll = useCallback(() => {
        setSelected({});
        setReplacements({});
        if (project && report) clearApproval(project.name, report.round);
      }, [project, report]);

      const applySelected = useCallback(async () => {
        if (!project || !report) return;
        const decisions = Object.keys(selected).map((id) => ({
          id,
          decision: 'approve',
          replacement: (replacements[id] || '').trim(),
        }));
        if (!decisions.length) {
          setError('还没有勾选任何候选项');
          return;
        }
        setBusy('apply');
        setError('');
        try {
          const data = await api('apply', { project: project.name, round: report.round, decisions });
          if (data.ok === false) throw new Error(data.error || '应用失败');
          setApplyResult(data);
          // 应用成功：清掉本地勾选，避免下一次打开面板带着旧勾选再点一次。
          clearApproval(project.name, report.round);
          setSelected({});
          setReplacements({});
          const detail = await api('project', { project: project.name });
          setProject(detail.project);
          setMarkdown(detail.project.markdown || null);
          setTab('approve');
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy('');
        }
      }, [project, report, selected, replacements]);

      // 首屏失败要先看得见：错误态优先于下面的「加载中」早退，并给一个重试入口。
      if (error && projects === null) {
        return h('div', { className: 'nf-root' },
          h('style', null, CSS),
          h('div', { className: 'nf-head' },
            h(ForgeLogo),
            h('div', null,
              h('div', { className: 'nf-title' }, '小说工坊'),
              h('div', { className: 'nf-sub' }, '面向中文小说的通用优化工作台'),
            ),
          ),
          h('div', { className: 'nf-body' },
            h('div', { className: 'nf-err' }, '加载失败：' + error),
            h('div', { className: 'nf-row' },
              h('button', { className: 'nf-btn primary', disabled: !!busy, onClick: bootstrap }, busy ? '重试中…' : '重试'),
            ),
            h('div', { className: 'nf-hint' },
              '面板走同源 /novel-forge/api：Host 半没启动、路由没注册、数据目录不可读都会落到这里。',
            ),
          ),
        );
      }

      if (projects === null) {
        return h('div', { className: 'nf-root' },
          h('style', null, CSS),
          h('div', { className: 'nf-loading' }, '小说工坊加载中…'),
        );
      }

      const selectedCount = Object.keys(selected).length;
      return h(
        'div',
        { className: 'nf-root' },
        h('style', null, CSS),
        h('div', { className: 'nf-head' },
          h(ForgeLogo),
          h('div', null,
            h('div', { className: 'nf-title' }, '小说工坊'),
            h('div', { className: 'nf-sub' },
              project ? `${project.config.title} · 主稿 ${project.config.main_draft} · ${report ? report.round : '未扫描'}` : '面向中文小说的通用优化工作台',
            ),
          ),
          h('div', { className: 'nf-spacer' }),
          busy ? h('span', { className: 'nf-muted', style: { fontSize: 11.5 } }, '处理中…') : null,
          h('button', { className: 'nf-btn', disabled: !!busy || !project, onClick: scan }, '扫描主稿'),
          h('button', {
            className: 'nf-btn primary', disabled: !!busy || !selectedCount, onClick: applySelected,
          }, selectedCount ? `应用已批准（${selectedCount}）` : '应用已批准'),
        ),
        h('div', { className: 'nf-tabs' },
          TABS.map(([key, label]) =>
            h('button', {
              key,
              className: `nf-tab ${tab === key ? 'on' : ''}`,
              onClick: () => setTab(key),
            }, key === 'approve' && selectedCount ? `${label} · ${selectedCount}` : label),
          ),
        ),
        h('div', { className: 'nf-body' },
          error ? h('div', { className: 'nf-err' }, error) : null,
          tab === 'project'
            ? h(ProjectTab, {
                projects, project, report, health, healthError, busy,
                onOpen: openProject, onScan: scan, onTab: setTab,
              })
            : null,
          tab === 'report'
            ? h(ReportTab, {
                report, selected, replacements, onToggle: toggle, onReplacement: setReplacement,
                rounds: project ? project.rounds : [], onRound: openRound,
              })
            : null,
          tab === 'approve'
            ? h(ApproveTab, {
                report, selected, replacements, applyResult, busy, markdown,
                onApply: applySelected, onClear: clearAll, onToggle: toggle, onReplacement: setReplacement,
              })
            : null,
          tab === 'kb'
            ? h(KbTab, { project })
            : null,
          tab === 'plot'
            ? h(PlotTab, { project })
            : null,
          tab === 'style'
            ? h(StyleTab, { project })
            : null,
        ),
      );
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('main', () =>
          ctx.slots.register({ name: 'main', key: 'novel-forge' }, () => h(Boundary, null, h(App))),
        );
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: 'novel-forge', order: 30, label: () => '小说工坊' }, ForgeIcon),
        );
      },
    };
  },
});
