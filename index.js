/**
 * 小说工坊 · Host 半
 *
 * 职责：
 *  - 把 Python 引擎（engine/run.py）作为子进程调用，做扫描 / 评分 / 应用 / 体检；
 *  - 给 Web GUI 提供 /novel-forge/api 路由（Client 半用 fetch 调用）；
 *  - 给聊天里的 Agent 注册 novel_* 工具（和 UI 走同一套 Host 方法）。
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_DIR = HERE;
const ENGINE_DIR = path.join(PLUGIN_DIR, 'engine');
const ENGINE_VERSION = '0.1.0';
const ROUTE = '/novel-forge';

// GET 只放只读动作：写操作（scan / apply / kb_sync / plot import / style learn …）必须 POST。
const READ_ONLY_ACTIONS = new Set([
  'health', 'projects', 'project', 'report', 'chapter', 'verify',
  'rewrite_list', 'kb_list', 'kb_search', 'kb_context',
]);

function readPluginConfig() {
  try {
    return JSON.parse(readFileSync(path.join(PLUGIN_DIR, 'plugin-config.json'), 'utf8'));
  } catch {
    return {};
  }
}

const PLUGIN_CONFIG = readPluginConfig();
const DATA_ROOT = path.resolve(
  process.env.NOVEL_FORGE_DATA ||
    PLUGIN_CONFIG.dataRoot ||
    path.join(PLUGIN_DIR, '..', '小说工坊'),
);
const PROJECTS_ROOT = path.join(DATA_ROOT, 'projects');
try {
  mkdirSync(PROJECTS_ROOT, { recursive: true });
} catch {
  /* read-only deployment: API will report it */
}

// ---------------------------------------------------------------- Python 运行时
let cachedPython = null;

function detectPython() {
  if (cachedPython) return cachedPython;
  if (process.env.NOVEL_FORGE_PYTHON) return (cachedPython = process.env.NOVEL_FORGE_PYTHON);
  if (PLUGIN_CONFIG.python) return (cachedPython = PLUGIN_CONFIG.python);
  const candidates = [];
  const runtimes = path.join(os.homedir(), '.dsh', 'dsh-runtimes');
  try {
    for (const name of readdirSync(runtimes)) {
      candidates.push(path.join(runtimes, name, 'dependencies', 'python', 'python.exe'));
    }
  } catch {
    /* 没有 DSH 运行时目录 */
  }
  candidates.push(path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Python', 'Python312', 'python.exe'));
  for (const candidate of candidates) {
    if (existsSync(candidate)) return (cachedPython = candidate);
  }
  return (cachedPython = process.platform === 'win32' ? 'python.exe' : 'python3');
}

function runEngine(args, { stdin = null, timeoutMs = 240000 } = {}) {
  return new Promise((resolve) => {
    const python = detectPython();
    let child;
    try {
      child = spawn(python, [path.join(ENGINE_DIR, 'run.py'), ...args], {
        cwd: ENGINE_DIR,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (error) {
      resolve({ ok: false, error: `无法启动 Python（${python}）：${error.message}` });
      return;
    }
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => {
      try {
        child.kill();
      } catch {
        /* ignore */
      }
      finish({ ok: false, error: `引擎超时（${Math.round(timeoutMs / 1000)} 秒）`, stderr: stderr.slice(-3000) });
    }, timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      if (stdout.length > 24 * 1024 * 1024) {
        try {
          child.kill();
        } catch {
          /* ignore */
        }
        finish({ ok: false, error: '引擎输出过大（>24MB）' });
      }
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
      if (stderr.length > 40000) stderr = stderr.slice(-20000);
    });
    child.on('error', (error) => {
      finish({ ok: false, error: `无法启动 Python（${python}）：${error.message}` });
    });
    child.on('close', () => {
      const text = stdout.trim();
      if (!text) {
        finish({ ok: false, error: '引擎没有输出', stderr: stderr.slice(-4000) });
        return;
      }
      try {
        finish(JSON.parse(text));
      } catch (error) {
        finish({
          ok: false,
          error: `引擎输出不是 JSON：${error.message}`,
          stdout: text.slice(0, 2000),
          stderr: stderr.slice(-4000),
        });
      }
    });
    try {
      child.stdin.end(stdin == null ? '' : stdin);
    } catch {
      /* ignore */
    }
  });
}

// ---------------------------------------------------------------- 项目
function safeProjectDir(name) {
  if (!name || typeof name !== 'string') throw new Error('缺少项目名');
  const dir = path.resolve(PROJECTS_ROOT, name);
  if (!dir.startsWith(PROJECTS_ROOT + path.sep)) throw new Error('非法项目名');
  if (!existsSync(path.join(dir, 'config.json'))) throw new Error(`项目不存在：${name}`);
  return dir;
}

function readJson(file, fallback = null) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

// GET /novel-forge/api?x=false 这类查询串参数全是字符串，布尔字段必须先归一，
// 否则 "false" 会被当成真值（曾经的番外剧透卡泄露就是这么来的）。
function toBool(value) {
  if (typeof value === 'boolean') return value;
  if (value == null) return false;
  const text = String(value).trim().toLowerCase();
  return text === '1' || text === 'true' || text === 'yes' || text === 'on';
}

function listRoundDirs(projectDir) {
  const roundsRoot = path.join(projectDir, 'rounds');
  if (!existsSync(roundsRoot)) return [];
  return readdirSync(roundsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^第\d+轮$/.test(entry.name))
    .map((entry) => ({ name: entry.name, number: Number(entry.name.match(/\d+/)[0]), dir: path.join(roundsRoot, entry.name) }))
    .sort((a, b) => a.number - b.number);
}

function latestScan(projectDir) {
  const rounds = listRoundDirs(projectDir).reverse();
  for (const round of rounds) {
    const report = readJson(path.join(round.dir, '扫描.json'));
    if (report) return { round: round.name, report, markdown: path.join(round.dir, '改动清单.md') };
  }
  return null;
}

function projectSummary(name) {
  const dir = safeProjectDir(name);
  const cfg = readJson(path.join(dir, 'config.json'), {});
  const status = readJson(path.join(dir, 'status.json'), {});
  const rounds = listRoundDirs(dir);
  const scan = latestScan(dir);
  const findings = scan?.report?.findings || [];
  return {
    name,
    title: cfg.title || name,
    dir,
    mainDraft: cfg.main_draft,
    currentRound: cfg.current_round || 0,
    rounds: rounds.length,
    score: scan?.report?.score?.total ?? null,
    grade: scan?.report?.score?.grade ?? null,
    stats: scan?.report?.stats ?? null,
    findingCount: findings.length,
    warns: findings.filter((f) => f.severity === 'warn').length,
    hard: findings.filter((f) => f.severity === 'hard').length,
    latestRound: scan?.round ?? null,
    lastScanAt: status.last_scan_at ?? null,
    lastApplyRound: status.last_apply_round ?? null,
    lastDraft: status.last_draft ?? null,
  };
}

function listProjects() {
  if (!existsSync(PROJECTS_ROOT)) return [];
  return readdirSync(PROJECTS_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith('_') && existsSync(path.join(PROJECTS_ROOT, entry.name, 'config.json')))
    .map((entry) => projectSummary(entry.name))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
}

function resolveProjectName(name) {
  if (name) return name;
  const projects = listProjects();
  if (!projects.length) throw new Error('还没有任何项目');
  return projects[0].name;
}

function projectDetail(name) {
  const dir = safeProjectDir(name);
  const cfg = readJson(path.join(dir, 'config.json'), {});
  const status = readJson(path.join(dir, 'status.json'), {});
  const rounds = listRoundDirs(dir).map((round) => ({
    name: round.name,
    hasScan: existsSync(path.join(round.dir, '扫描.json')),
    hasApply: existsSync(path.join(round.dir, '应用记录.json')),
    draft: (() => {
      const draft = path.join(round.dir, `稿子_${round.name}.docx`);
      return existsSync(draft) ? draft : null;
    })(),
  }));
  const scan = latestScan(dir);
  const kbIndex = readJson(path.join(dir, 'kb', 'index.json'));
  return {
    name,
    config: cfg,
    status,
    rounds,
    latestRound: scan?.round ?? null,
    report: scan?.report ?? null,
    markdown: scan?.markdown ?? null,
    kb: kbIndex
      ? {
          cards: (kbIndex.cards || []).length,
          sources: (kbIndex.sources || []).length,
          spoilerCards: (kbIndex.cards || []).filter((card) => card.spoiler).length,
          generatedAt: kbIndex.generated_at,
        }
      : null,
  };
}

async function scanProject(name) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const result = await runEngine(['scan', '--project', dir]);
  return { projectName, result };
}

// 改动清单正文预览：两条通道（工具 + HTTP）都只回前 4000 字符，
// 既让 Agent 能读到清单内容，又不把整篇 md 塞进返回值。
const MARKDOWN_PREVIEW_CHARS = 4000;

function markdownPreview(dir) {
  const file = path.join(dir, '改动清单.md');
  if (!existsSync(file)) return null;
  const text = readFileSync(file, 'utf8');
  return text.length > MARKDOWN_PREVIEW_CHARS
    ? text.slice(0, MARKDOWN_PREVIEW_CHARS) + '\n……（已截断，全文见 改动清单.md）'
    : text;
}

async function reportProject(name, round) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const rounds = listRoundDirs(dir).reverse();
  // 不指定轮次时回退到「最近一个有扫描结果的轮次」，而不是最新目录——
  // 新开的空轮次不该让上一轮的扫描报告变得不可读。
  const target = round
    ? rounds.find((entry) => entry.name === round)
    : rounds.find((entry) => existsSync(path.join(entry.dir, '扫描.json')));
  if (!target) throw new Error(round ? `${round} 没有扫描结果` : '还没有扫描结果');
  const report = readJson(path.join(target.dir, '扫描.json'));
  if (!report) throw new Error(`${target.name} 没有扫描结果`);
  return { round: target.name, report, dir: target.dir, markdown: path.join(target.dir, '改动清单.md') };
}

async function applyProject(name, round, decisions) {
  // 空/非法的 decisions 一律拒绝：以前空数组也照跑整套应用 + 体检，
  // 会在 rounds/ 下开出一个新轮次并改写 status.last_apply_round（等于空点一下就动了稿）。
  // 只把 decision === 'approve' 的条目前置过滤掉：全部 reject 时不再下发给引擎，
  // 否则引擎虽会跳过它们，但仍会归档旧产物、写出新轮次。
  const list = Array.isArray(decisions)
    ? decisions.filter((entry) =>
        entry && typeof entry === 'object' && entry.id && entry.decision === 'approve')
    : [];
  if (!list.length) {
    return { ok: false, error: '没有批准任何条目：应用已取消（不会生成新稿，也不会开新轮次）' };
  }
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const decisionsPayload = JSON.stringify({ decisions: list });
  const args = ['apply', '--project', dir, '--decisions', '-'];
  if (round) args.push('--round', round);
  return runEngine(args, { stdin: decisionsPayload });
}

async function verifyProject(name, round) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const rounds = listRoundDirs(dir).reverse();
  // 同上：不指定轮次时回退到最近一个真的做过体检的轮次。
  const target = round
    ? rounds.find((entry) => entry.name === round)
    : rounds.find((entry) => existsSync(path.join(entry.dir, '体检.json')));
  if (!target) throw new Error(round ? `${round} 没有可体检的结果` : '还没有可体检的轮次');
  const gates = readJson(path.join(target.dir, '体检.json'));
  if (!gates) throw new Error(`${target.name} 还没有体检结果，请先应用审批`);
  return { round: target.name, verify: gates };
}

async function readChapter(name, chapter, maxChars) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const result = await runEngine(['dump', '--project', dir, '--chapter', String(chapter)]);
  if (result?.ok === false) return result;
  const data = result.chapters?.[0];
  if (!data) throw new Error(`没有第 ${chapter} 章`);
  const full = data.paragraphs.map((p) => p.text).join('\n');
  const limit = Math.max(1000, Math.min(20000, Number(maxChars) || 8000));
  return {
    chapter: data.index,
    title: data.title,
    chars: full.length,
    truncated: full.length > limit,
    text: full.length > limit ? full.slice(0, limit) + '\n……（已截断）' : full,
  };
}

// ---------------------------------------------------------------- A.6 改写契约
async function rewritePrepare(name, findingId, round) {
  const projectName = resolveProjectName(name);
  if (!findingId) throw new Error('缺少 finding_id');
  const dir = safeProjectDir(projectName);
  const args = ['rewrite', '--project', dir, '--action', 'prepare', '--finding', String(findingId)];
  if (round) args.push('--round', round);
  return runEngine(args);
}

async function rewriteSubmit(name, requestId, text, round) {
  const projectName = resolveProjectName(name);
  if (!requestId) throw new Error('缺少 request_id');
  if (typeof text !== 'string' || !text.trim()) throw new Error('缺少改写文本');
  const dir = safeProjectDir(projectName);
  const args = ['rewrite', '--project', dir, '--action', 'submit', '--request', String(requestId), '--text', '-'];
  if (round) args.push('--round', round);
  return runEngine(args, { stdin: text });
}

async function rewriteList(name, round) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const args = ['rewrite', '--project', dir, '--action', 'list'];
  if (round) args.push('--round', round);
  return runEngine(args);
}

// ---------------------------------------------------------------- P1 知识库
async function kbSync(name) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  return runEngine(['kb', '--project', dir, '--action', 'sync']);
}

async function kbList(name, includeSpoilers) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const args = ['kb', '--project', dir, '--action', 'list'];
  if (includeSpoilers) args.push('--include-spoilers');
  return runEngine(args);
}

async function kbSearch(name, query, limit, includeSpoilers) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const args = ['kb', '--project', dir, '--action', 'search', '--query', String(query || ''), '--limit', String(limit || 8)];
  if (includeSpoilers) args.push('--include-spoilers');
  return runEngine(args);
}

async function kbContext(name, chapter, maxChars, includeSpoilers) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const args = ['kb', '--project', dir, '--action', 'context', '--chapter', String(chapter), '--max-chars', String(maxChars || 4000)];
  if (includeSpoilers) args.push('--include-spoilers');
  return runEngine(args);
}

// ---------------------------------------------------------------- P3 伏笔账 + 续写闭环（2026-11-03 新增）
// 伏笔账落在 <项目>/plot/伏笔.json，纯 JS 维护，不依赖 Python 引擎。
// 续写闭环：prepare 凑齐「上一章正文 + 未回收伏笔 + 设定上下文 + 写作要求」，
// 提交时只做落盘与轻量自检（字数/段数/对话比/章末弱钩子），不自动改主稿。
const FORESHADOW_REL = path.join('plot', '伏笔.json');
const WEAK_HOOK_HINTS = ['闭上了眼睛', '闭上眼睛', '仿佛', '从来没有发生过', '尽快到达', '只能加快', '深吸了一口气'];
const CJK_RE = /[\u4e00-\u9fff]/g;
const cjkCount = (text) => (String(text).match(CJK_RE) || []).length;

function foreshadowFile(dir) {
  return path.join(dir, FORESHADOW_REL);
}

function readForeshadow(dir) {
  const data = readJson(foreshadowFile(dir), null);
  if (data && Array.isArray(data.items)) return { version: 1, current_chapter: 0, ...data };
  return { version: 1, current_chapter: 0, items: [] };
}

function writeForeshadow(dir, ledger) {
  const file = foreshadowFile(dir);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(ledger, null, 2), 'utf8');
}

function foreshadowNextId(items) {
  let max = 0;
  for (const item of items) {
    const hit = /^FS-(\d+)$/.exec(String(item?.id || ''));
    if (hit) max = Math.max(max, Number(hit[1]));
  }
  return 'FS-' + String(max + 1).padStart(3, '0');
}

function foreshadowView(items, currentChapter) {
  const cur = Number(currentChapter) || 0;
  return items
    .map((item) => ({
      id: item.id,
      text: item.text,
      chapter: item.chapter ?? null,
      status: item.status || 'open',
      paid_chapter: item.paid_chapter ?? null,
      tags: item.tags || [],
      note: item.note || '',
      age: cur && item.chapter ? cur - Number(item.chapter) : null,
    }))
    .sort((a, b) => Number(a.chapter || 0) - Number(b.chapter || 0));
}

function currentChapterOf(dir) {
  const scan = latestScan(dir);
  const scanChapters = scan?.report?.chapters?.length || 0;
  const ledger = readForeshadow(dir);
  return Math.max(scanChapters, Number(ledger.current_chapter) || 0);
}

async function foreshadowAction(name, payload) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const op = String(payload?.op || 'list');
  const ledger = readForeshadow(dir);
  const now = new Date().toISOString();
  const current = Number(payload?.current_chapter) || currentChapterOf(dir);

  if (op === 'add') {
    const text = String(payload?.text || '').trim();
    if (!text) throw new Error('add 需要 text（这条伏笔写的是什么）');
    const item = {
      id: foreshadowNextId(ledger.items),
      text,
      chapter: Number(payload?.chapter) || current || null,
      status: 'open',
      paid_chapter: null,
      tags: Array.isArray(payload?.tags) ? payload.tags : [],
      note: String(payload?.note || ''),
      created_at: now,
      updated_at: now,
    };
    ledger.items.push(item);
    ledger.current_chapter = current || ledger.current_chapter || 0;
    writeForeshadow(dir, ledger);
    return { ok: true, op, item, total: ledger.items.length };
  }

  if (op === 'pay') {
    const item = ledger.items.find((entry) => entry.id === payload?.id);
    if (!item) throw new Error(`没有这条伏笔：${payload?.id}`);
    item.status = 'paid';
    item.paid_chapter = Number(payload?.chapter) || current || null;
    item.note = payload?.note != null ? String(payload.note) : item.note;
    item.updated_at = now;
    writeForeshadow(dir, ledger);
    return { ok: true, op, item };
  }

  if (op === 'reopen') {
    const item = ledger.items.find((entry) => entry.id === payload?.id);
    if (!item) throw new Error(`没有这条伏笔：${payload?.id}`);
    item.status = 'open';
    item.paid_chapter = null;
    item.updated_at = now;
    writeForeshadow(dir, ledger);
    return { ok: true, op, item };
  }

  if (op === 'update') {
    const item = ledger.items.find((entry) => entry.id === payload?.id);
    if (!item) throw new Error(`没有这条伏笔：${payload?.id}`);
    if (payload?.text != null) item.text = String(payload.text);
    if (payload?.note != null) item.note = String(payload.note);
    if (payload?.chapter != null) item.chapter = Number(payload.chapter);
    if (Array.isArray(payload?.tags)) item.tags = payload.tags;
    item.updated_at = now;
    writeForeshadow(dir, ledger);
    return { ok: true, op, item };
  }

  if (op === 'remove') {
    const before = ledger.items.length;
    ledger.items = ledger.items.filter((entry) => entry.id !== payload?.id);
    if (ledger.items.length === before) throw new Error(`没有这条伏笔：${payload?.id}`);
    writeForeshadow(dir, ledger);
    return { ok: true, op, removed: payload?.id, total: ledger.items.length };
  }

  if (op === 'gaps') {
    // 按「埋了多久还没回收」排，最该先处理第一顺位
    const open = foreshadowView(ledger.items.filter((item) => (item.status || 'open') !== 'paid'), current);
    const stale = open.filter((item) => item.age != null && item.age >= (Number(payload?.min_age) || 5));
    return {
      ok: true,
      op,
      current_chapter: current,
      open_count: open.length,
      stale_count: stale.length,
      stale: stale.sort((a, b) => (b.age || 0) - (a.age || 0)),
      open,
    };
  }

  // list（默认）
  const status = String(payload?.status || 'all');
  let items = foreshadowView(ledger.items, current);
  if (status === 'open') items = items.filter((item) => (item.status || 'open') !== 'paid');
  if (status === 'paid') items = items.filter((item) => item.status === 'paid');
  return {
    ok: true,
    op: 'list',
    status,
    current_chapter: current,
    total: ledger.items.length,
    open_count: ledger.items.filter((item) => (item.status || 'open') !== 'paid').length,
    items,
    file: foreshadowFile(dir),
  };
}

async function continuePrepare(name, payload) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const scan = latestScan(dir);
  const totalChapters = scan?.report?.chapters?.length || 0;
  const after = Number(payload?.after_chapter) || totalChapters;
  const previous = Math.max(1, after);
  const next = previous + 1;

  let previousInfo = null;
  if (totalChapters > 0) {
    try {
      previousInfo = await readChapter(projectName, previous, Number(payload?.max_prev_chars) || 9000);
    } catch (error) {
      previousInfo = { error: error?.message || String(error) };
    }
  }

  let kb = null;
  try {
    const kbResult = await kbContext(projectName, next, Number(payload?.kb_chars) || 3000, false);
    kb = kbResult?.ok === false ? null : kbResult;
  } catch {
    kb = null;
  }

  const ledger = readForeshadow(dir);
  const openItems = foreshadowView(ledger.items.filter((item) => (item.status || 'open') !== 'paid'), previous);
  const staleItems = openItems.filter((item) => item.age != null && item.age >= 5);

  const prevText = previousInfo?.text || '';
  const tail = prevText.split('\n').map((line) => line.trim()).filter(Boolean).slice(-5).join('\n');

  const promptLines = [
    `为《${readJson(path.join(dir, 'config.json'), {}).title || projectName}》续写第 ${next} 章。`,
    '硬要求：',
    '1) 语气、句长、对白密度接着上一章，不要突然变书面腔。',
    '2) 章末落在具体动作、决定或新信息上；不要用「闭上了眼睛」「仿佛……从来没有发生过」这类收束句。',
    '3) 至少推进一条下面的未回收伏笔，或明确说明本章为何不推进（别装作没看见）。',
    '4) 不新增未登记的重要设定；要用新设定就先说出来，别偷偷塞。',
  ];
  if (staleItems.length) {
    promptLines.push(`5) 这几条伏笔拖了 5 章以上，优先挑一条回收：${staleItems.map((item) => `${item.id}（第${item.chapter}章埋，已隔 ${item.age} 章）`).join('；')}`);
  }

  return {
    ok: true,
    project: projectName,
    next_chapter: next,
    previous_chapter: previous,
    previous_chars: prevText ? cjkCount(prevText) : 0,
    previous_tail: tail,
    previous_text: prevText,
    open_foreshadow: openItems,
    stale_foreshadow: staleItems,
    context: kb,
    prompt: promptLines.join('\n'),
    hint: '写好后用 novel_continue(action=submit, text=..., chapter=' + next + ') 落盘，工具会回字数/段数/章末检查结果。',
  };
}

async function continueSubmit(name, payload) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const text = String(payload?.text || '').trim();
  if (!text) throw new Error('submit 需要 text（续写正文）');
  const chapter = Number(payload?.chapter) || currentChapterOf(dir) + 1;
  const outDir = path.join(dir, 'drafts', '续写');
  mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 12);
  const file = path.join(outDir, `第${chapter}章_${stamp}.md`);
  writeFileSync(file, `# 第${chapter}章\n\n${text}\n`, 'utf8');

  const paras = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const dialogueParas = paras.filter((line) => /[“”「」"]/.test(line)).length;
  const lastPara = paras[paras.length - 1] || '';
  const weakHits = WEAK_HOOK_HINTS.filter((word) => lastPara.includes(word));
  const lastShort = cjkCount(lastPara) <= 8;

  return {
    ok: true,
    project: projectName,
    chapter,
    file,
    chars: cjkCount(text),
    paragraphs: paras.length,
    dialogue_ratio: paras.length ? Number((dialogueParas / paras.length).toFixed(3)) : 0,
    last_paragraph: lastPara,
    hook_check: {
      weak: weakHits.length > 0 || lastShort,
      hits: weakHits,
      too_short: lastShort,
      advice: weakHits.length || lastShort
        ? '章末偏弱：换成具体动作/决定/新信息的落点，别停在总结或极短句上。'
        : '章末落点看着还行。',
    },
    next: '满意就用 novel_apply 之外的手工流程并入主稿；这条只落在 drafts/续写/，不动主稿。',
  };
}

// 相对路径统一按项目目录解析：引擎的 cwd 是 engine/，直接透传会按插件目录找，必然找不到。
function resolveUserPath(projectDir, value) {
  const raw = String(value);
  return path.isAbsolute(raw) ? raw : path.resolve(projectDir, raw);
}

async function plotAction(name, payload) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const action = payload?.action;
  if (!action) throw new Error('缺少 plot action');
  const args = ['plot', '--project', dir, '--action', action];
  if (payload.chapter_key) args.push('--chapter-key', String(payload.chapter_key));
  if (payload.source) args.push('--source', resolveUserPath(dir, payload.source));
  if (payload.title) args.push('--title', String(payload.title));
  if (payload.total_chars) args.push('--total-chars', String(payload.total_chars));
  if (action === 'submit') {
    return runEngine([...args, '--payload', '-'], { stdin: JSON.stringify(payload.payload || {}) });
  }
  return runEngine(args);
}

async function styleAction(name, payload) {
  const projectName = resolveProjectName(name);
  const dir = safeProjectDir(projectName);
  const action = payload?.action;
  if (!action) throw new Error('缺少 style action');
  const args = ['style', '--project', dir, '--action', action];
  if (payload.name) args.push('--name', String(payload.name));
  if (action === 'learn') {
    const samples = Array.isArray(payload.samples) ? payload.samples : [];
    if (!samples.length) throw new Error('style learn 需要 samples 文件路径');
    args.push('--samples', ...samples.map((item) => resolveUserPath(dir, item)));
  }
  if (payload.text != null) args.push('--text', String(payload.text));
  if (payload.text_file) args.push('--text-file', resolveUserPath(dir, payload.text_file));
  if (payload.chapter) args.push('--chapter', String(payload.chapter));
  if (payload.para != null) args.push('--para', String(payload.para));
  return runEngine(args);
}

// ---------------------------------------------------------------- 工具摘要
function summarizeReport(report, { limit = 12, chapter = null } = {}) {
  const allFindings = report.findings || [];
  const findings = allFindings.filter((f) => !(f.meta && f.meta.audit)).filter((f) => (chapter ? f.chapter === chapter : true));
  const order = { hard: 0, warn: 1, info: 2 };
  const sorted = [...findings].sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3) || a.chapter - b.chapter || a.para - b.para);
  const compact = sorted.slice(0, limit).map((f) => ({
    id: f.id,
    severity: f.severity,
    category: f.category,
    rule: f.rule,
    location: `第${f.chapter}章·第${f.para_display}段`,
    quote: f.quote.length > 120 ? f.quote.slice(0, 120) + '…' : f.quote,
    why: f.why,
    suggestion: f.suggestion,
    action: f.action,
    auto_fixable: f.auto_fixable,
  }));
  const audit = report.audit || null;
  const auditFindings = allFindings.filter((f) => f.meta && f.meta.audit);
  return {
    ok: true,
    round: report.round,
    stats: report.stats,
    score: report.score,
    findingCount: findings.length,
    auditFindingCount: auditFindings.length,
    // 同轮重复扫描时引擎会把上一版产物移进 历史/，这里透出备份路径提示调用方。
    rescan_backup: report.artifacts && Array.isArray(report.artifacts.archived) && report.artifacts.archived.length
      ? report.artifacts.archived
      : null,
    severityCounts: {
      hard: findings.filter((f) => f.severity === 'hard').length,
      warn: findings.filter((f) => f.severity === 'warn').length,
      info: findings.filter((f) => f.severity === 'info').length,
    },
    audit: audit
      ? {
          engine: audit.engine,
          policy: audit.policy,
          metrics: (audit.metrics || []).map((m) => ({
            id: m.id,
            name: m.name,
            enabled: m.enabled,
            book_value: m.book_value,
            baseline_value: m.baseline_value,
            deviation_pct: m.deviation_pct,
            default_zones: m.default_zones,
            policy: m.policy,
          })),
          notes: audit.notes,
        }
      : null,
    findings: compact,
    artifacts: report.artifacts || null,
  };
}

const TOOL_OUTPUT = {
  schema: { type: 'object', additionalProperties: true },
  render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }],
};

function toolDecisions() {
  return {
    type: 'object',
    properties: {
      id: { type: 'string', description: '候选项 id（F-xxxx）' },
      decision: { type: 'string', enum: ['approve', 'reject'], description: 'approve=应用，reject=不应用' },
      replacement: { type: 'string', description: '整段替换文本；留空表示只记录不做文本改动' },
      action: { type: 'string', enum: ['flag', 'delete', 'replace'], description: '动作，默认沿用扫描建议' },
    },
    required: ['id', 'decision'],
    additionalProperties: false,
  };
}

function buildTools() {
  return [
    {
      name: 'novel_project',
      description: '小说工坊：列出书项目或查看某个项目的状态（章/段/字、轮次、评分、待办）。',
      parameters: {
        type: 'object',
        properties: {
          action: { type: 'string', enum: ['list', 'status'], description: 'list=列出项目，status=查看项目状态' },
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        const action = args?.action || 'list';
        if (action === 'list') return { ok: true, projects: listProjects(), dataRoot: DATA_ROOT };
        return { ok: true, project: projectDetail(resolveProjectName(args?.project)) };
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_scan',
      description: '小说工坊：扫描当前主稿，生成改动清单与编辑健康度评分（会写入项目的 rounds 目录）。返回分项评分和最需处理的候选项。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        const name = resolveProjectName(args?.project);
        const { result } = await scanProject(name);
        if (result?.ok === false) return result;
        return summarizeReport(result, { limit: 15 });
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_report',
      description: '小说工坊：读取扫描报告。可按章筛选，查看候选项的位置、原文片段、理由和建议改法。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          round: { type: 'string', description: '轮次名，缺省用最新一轮' },
          chapter: { type: 'integer', description: '只看某一章' },
          limit: { type: 'integer', description: '最多返回多少条候选项（默认 15，最多 60）' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        const { round, report, dir } = await reportProject(args?.project, args?.round);
        return {
          ...summarizeReport({ ...report, round }, { limit: Math.min(60, Math.max(1, args?.limit || 15)), chapter: args?.chapter || null }),
          // 与 HTTP 通道保持同义：markdown 是清单路径，markdown_preview 是前 4000 字正文。
          markdown: path.join(dir, '改动清单.md'),
          markdown_preview: markdownPreview(dir),
        };
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_apply',
      description: '小说工坊：应用已批准的改动，生成新稿并自动跑门禁体检。decisions 里每条给出 id 和 decision；替换文本放 replacement（整段替换）。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          round: { type: 'string', description: '轮次名，缺省用最新一轮' },
          decisions: { type: 'array', items: toolDecisions(), description: '审批结果' },
        },
        required: ['decisions'],
        additionalProperties: false,
      },
      async execute(args) {
        const result = await applyProject(args?.project, args?.round, args?.decisions);
        if (result?.ok === false) return result;
        return {
          ok: true,
          round: result.round,
          output: result.output,
          applied: result.applied,
          delta_cjk: result.delta_cjk,
          expected_delta: result.expected_delta,
          stats_after: result.stats_after,
          reapply: result.reapply || null,
          verify_pass: result.verify?.pass,
          gates: result.verify?.gates,
          changes: (result.changes || []).slice(0, 20).map((c) => ({ id: c.id, chapter: c.chapter, para: c.para + 1, kind: c.kind })),
        };
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_verify',
      description: '小说工坊：读取最近一次应用后的门禁体检结果（章结构/禁用词/引号/重复段/字数变化/改动生效/文风指纹）。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          round: { type: 'string', description: '轮次名，缺省用最新一轮' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        return verifyProject(args?.project, args?.round);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_read_chapter',
      description: '小说工坊：读取某一章正文（可按 maxChars 截断），用于语义审稿或人工核对。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          chapter: { type: 'integer', description: '章序号（1 起）' },
          maxChars: { type: 'integer', description: '最多返回多少字（默认 8000）' },
        },
        required: ['chapter'],
        additionalProperties: false,
      },
      async execute(args) {
        return readChapter(args?.project, args?.chapter, args?.maxChars);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_rewrite_prepare',
      description: '小说工坊：为某条候选项生成 A.6 定向改写请求（原文 / 触发指标 / 上下文 / 硬约束 / 可直接给模型用的 prompt）。只生成请求，不改稿。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          finding_id: { type: 'string', description: '候选项 id（F-xxxx）' },
          round: { type: 'string', description: '轮次名，缺省用最新一轮' },
        },
        required: ['finding_id'],
        additionalProperties: false,
      },
      async execute(args) {
        return rewritePrepare(args?.project, args?.finding_id, args?.round);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_rewrite_submit',
      description: '小说工坊：提交一段改写，按 A.6 机检（篇幅 / 禁用词 / 新数字 / 新实体 / 新对白 / AI 味复测）；通过则存为改写提案，不自动替换主稿。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          request_id: { type: 'string', description: 'novel_rewrite_prepare 返回的 request_id' },
          text: { type: 'string', description: '改写后的整段正文' },
          round: { type: 'string', description: '轮次名，缺省自动查找' },
        },
        required: ['request_id', 'text'],
        additionalProperties: false,
      },
      async execute(args) {
        return rewriteSubmit(args?.project, args?.request_id, args?.text, args?.round);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_rewrite_list',
      description: '小说工坊：列出本轮所有通过机检、等待审批的改写提案。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          round: { type: 'string', description: '轮次名，缺省用最新一轮' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        return rewriteList(args?.project, args?.round);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_kb_sync',
      description: '小说工坊：同步知识库设定集（解析 kb/sources 下的 txt/md/docx → 卡片 + 索引）。改过设定文件后重新运行。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        return kbSync(args?.project);
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_kb_list',
      description: '小说工坊：列出知识库卡片与来源（默认不返回番外剧透卡）。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          include_spoilers: { type: 'boolean', description: '是否包含番外剧透卡' },
        },
        additionalProperties: false,
      },
      async execute(args) {
        return kbList(args?.project, toBool(args?.include_spoilers));
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_kb_search',
      description: '小说工坊：在知识库里本地检索设定（返回标题、来源、权威等级、片段）。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          query: { type: 'string', description: '检索词，如「力量体系」「人物身份」「引路灯」' },
          limit: { type: 'integer', description: '最多返回条数（默认 8）' },
          include_spoilers: { type: 'boolean', description: '是否包含番外剧透卡' },
        },
        required: ['query'],
        additionalProperties: false,
      },
      async execute(args) {
        return kbSearch(args?.project, args?.query, args?.limit, toBool(args?.include_spoilers));
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_kb_context',
      description: '小说工坊：为某一章生成知识库上下文包（按章内实体召回相关设定卡；番外默认排除）。续写/审稿时先取这个，不要塞全书。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          chapter: { type: 'integer', description: '章序号（1 起）' },
          maxChars: { type: 'integer', description: '上下文包字数上限（默认 4000）' },
          include_spoilers: { type: 'boolean', description: '是否包含番外剧透卡（默认 false）' },
        },
        required: ['chapter'],
        additionalProperties: false,
      },
      async execute(args) {
        return kbContext(args?.project, args?.chapter, args?.maxChars, toBool(args?.include_spoilers));
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_plot',
      description: '小说工坊：情节拼接。action=import 解析作者细纲成节拍卡；validate 校验节拍（字数/禁忌/设定暴露/重复句/章末钩子）；list 列出现有节拍；template 返回"给剧情拆几节"的 JSON Schema + prompt；submit 校验并保存 AI 拆出的节拍 JSON。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          action: { type: 'string', enum: ['import', 'validate', 'list', 'template', 'submit'], description: '操作' },
          source: { type: 'string', description: 'import 用的细纲路径（md/txt）' },
          chapter_key: { type: 'string', description: '章键，如 第28章 / 第29章' },
          title: { type: 'string', description: 'import 时的标题' },
          total_chars: { type: 'integer', description: 'template 的整章字数预算（默认 2200）' },
          payload: { type: 'object', description: 'submit 时的节拍 JSON（chapter_key/beats/...）', additionalProperties: true },
        },
        required: ['action'],
        additionalProperties: false,
      },
      async execute(args) {
        return plotAction(args?.project, args || {});
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_style',
      description: '小说工坊：文风调性。action=list 列出风格档案；learn 用作者认可的样本学一个风格（samples 传文件路径数组）；check 计算文本/段落/章节对某风格的粘性，并给出与其他风格的相对排名。只做检测，不改稿。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          action: { type: 'string', enum: ['list', 'learn', 'check'], description: '操作' },
          name: { type: 'string', description: '风格名，如 散文 / 干句 / 诗性' },
          samples: { type: 'array', items: { type: 'string' }, description: 'learn 用的样本文件绝对路径' },
          text: { type: 'string', description: 'check 用的文本（也可用 text_file / chapter）' },
          text_file: { type: 'string', description: 'check 用的文本文件路径' },
          chapter: { type: 'integer', description: 'check 整章' },
          para: { type: 'integer', description: 'check 章内第 N 段（0 起）' },
        },
        required: ['action'],
        additionalProperties: false,
      },
      async execute(args) {
        return styleAction(args?.project, args || {});
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_foreshadow',
      description: '小说工坊：伏笔账。记录埋下的伏笔、标记回收、查“埋了很久还没收”的清单。op=add/list/pay/reopen/update/remove/gaps。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          op: { type: 'string', enum: ['add', 'list', 'pay', 'reopen', 'update', 'remove', 'gaps'], description: '操作，默认 list' },
          text: { type: 'string', description: 'add/update：这条伏笔写的是什么' },
          chapter: { type: 'integer', description: '埋在第几章（add 缺省=当前章）/ 回收在第几章（pay）' },
          id: { type: 'string', description: '伏笔编号，如 FS-001' },
          status: { type: 'string', enum: ['open', 'paid', 'all'], description: 'list 过滤，默认 all' },
          tags: { type: 'array', items: { type: 'string' }, description: '标签' },
          note: { type: 'string', description: '备注（打算怎么回收）' },
          min_age: { type: 'integer', description: 'gaps：隔多少章算“拖太久”，默认 5' },
          current_chapter: { type: 'integer', description: '当前进度章号（缺省按扫描结果推）' },
        },
        required: ['op'],
        additionalProperties: false,
      },
      async execute(args) {
        return foreshadowAction(args?.project, args || {});
      },
      output: TOOL_OUTPUT,
    },
    {
      name: 'novel_continue',
      description: '小说工坊：续写闭环。action=prepare 凑齐上一章正文、未回收伏笔、设定上下文和写作要求；action=submit 把写好的正文落到 drafts/续写/ 并自查字数、章末钩子。不改主稿。',
      parameters: {
        type: 'object',
        properties: {
          project: { type: 'string', description: '项目名（缺省用第一个项目）' },
          action: { type: 'string', enum: ['prepare', 'submit'], description: 'prepare=取上下文包，submit=提交续写' },
          after_chapter: { type: 'integer', description: 'prepare：接在第几章后面（缺省=最后一章）' },
          max_prev_chars: { type: 'integer', description: 'prepare：上一章最多带多少字，默认 9000' },
          kb_chars: { type: 'integer', description: 'prepare：设定上下文预算，默认 3000' },
          text: { type: 'string', description: 'submit：续写正文' },
          chapter: { type: 'integer', description: 'submit：这是第几章（缺省=当前章+1）' },
        },
        required: ['action'],
        additionalProperties: false,
      },
      async execute(args) {
        const action = args?.action || 'prepare';
        if (action === 'submit') return continueSubmit(args?.project, args || {});
        return continuePrepare(args?.project, args || {});
      },
      output: TOOL_OUTPUT,
    },
  ];
}

// ---------------------------------------------------------------- HTTP API
function sendJson(res, status, value) {
  try {
    const body = JSON.stringify(value);
    res.writeHead(status, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'content-length': Buffer.byteLength(body),
    });
    res.end(body);
  } catch (error) {
    try {
      res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
      res.end(String(error));
    } catch {
      /* ignore */
    }
  }
}

function readBody(req, limit = 8 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error('请求体过大'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

async function dispatch(payload) {
  const action = payload?.action;
  if (!action) throw new Error('缺少 action');
  switch (action) {
    case 'health':
      return {
        ok: true,
        plugin: 'novel-forge',
        version: ENGINE_VERSION,
        dataRoot: DATA_ROOT,
        python: detectPython(),
        projects: listProjects().length,
      };
    case 'projects':
      return { ok: true, dataRoot: DATA_ROOT, projects: listProjects() };
    case 'project': {
      const name = resolveProjectName(payload.project);
      return { ok: true, project: projectDetail(name) };
    }
    case 'scan': {
      const name = resolveProjectName(payload.project);
      const { result } = await scanProject(name);
      if (result?.ok === false) return result;
      return { ...result, ok: true };
    }
    case 'report': {
      const { round, report, dir, markdown } = await reportProject(payload.project, payload.round);
      return { ok: true, round, report, dir, markdown, markdown_preview: markdownPreview(dir) };
    }
    case 'apply': {
      const result = await applyProject(payload.project, payload.round, payload.decisions);
      return result?.ok === false ? result : { ...result, ok: true };
    }
    case 'verify': {
      const result = await verifyProject(payload.project, payload.round);
      return { ok: true, ...result };
    }
    case 'chapter': {
      const data = await readChapter(payload.project, payload.chapter, payload.maxChars ?? payload.max_chars);
      return { ok: true, ...data };
    }
    case 'rewrite_prepare': {
      const result = await rewritePrepare(payload.project, payload.finding_id, payload.round);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'rewrite_submit': {
      const result = await rewriteSubmit(payload.project, payload.request_id, payload.text, payload.round);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'rewrite_list': {
      const result = await rewriteList(payload.project, payload.round);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'kb_sync': {
      const result = await kbSync(payload.project);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'kb_list': {
      const result = await kbList(payload.project, toBool(payload.include_spoilers ?? payload.includeSpoilers));
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'kb_search': {
      if (!payload.query) throw new Error('kb_search 需要 query');
      const result = await kbSearch(payload.project, payload.query, payload.limit, toBool(payload.include_spoilers ?? payload.includeSpoilers));
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'kb_context': {
      if (!payload.chapter) throw new Error('kb_context 需要 chapter');
      // GUI 半发 maxChars，老调用发 max_chars；两种写法都认，别再静默丢掉。
      const maxChars = payload.maxChars ?? payload.max_chars;
      const result = await kbContext(payload.project, payload.chapter, maxChars, toBool(payload.include_spoilers ?? payload.includeSpoilers));
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'plot': {
      const result = await plotAction(payload.project, payload);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'style': {
      const result = await styleAction(payload.project, payload);
      return result?.ok === false ? result : { ok: true, ...result };
    }
    case 'foreshadow': {
      return foreshadowAction(payload.project, payload);
    }
    case 'continue': {
      if ((payload.action_sub || payload.sub) === 'submit' || payload.text) {
        return continueSubmit(payload.project, payload);
      }
      return continuePrepare(payload.project, payload);
    }
    default:
      throw new Error(`未知 action：${action}`);
  }
}

async function handleRequest(req, res) {
  try {
    const url = new URL(req.url || '/', 'http://127.0.0.1');
    if (req.method === 'GET' && url.pathname === `${ROUTE}/health`) {
      sendJson(res, 200, await dispatch({ action: 'health' }));
      return;
    }
    if (url.pathname !== `${ROUTE}/api`) {
      sendJson(res, 404, { ok: false, error: 'not found' });
      return;
    }
    if (req.method !== 'GET' && req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'method not allowed' });
      return;
    }
    let payload;
    if (req.method === 'POST') {
      const body = await readBody(req);
      payload = body ? JSON.parse(body) : {};
    } else {
      payload = Object.fromEntries(url.searchParams.entries());
      if (!READ_ONLY_ACTIONS.has(payload.action)) {
        sendJson(res, 405, {
          ok: false,
          error: `GET 只允许只读动作，${payload.action || '(缺少 action)'} 请改用 POST`,
        });
        return;
      }
    }
    const result = await dispatch(payload);
    sendJson(res, 200, result);
  } catch (error) {
    sendJson(res, 400, { ok: false, error: error?.message || String(error) });
  }
}

// ---------------------------------------------------------------- 插件入口
export const inject = ['tools'];

export function apply(ctx) {
  // 2026-11-03 修：新版宿主里 apply 阶段的 ctx.get('webServer') 取不到（服务由 cordis 注入，
  // 要等依赖就绪），原来这一句拿不到就直接跳过注册 → 面板永远 405。改成两条路都试。
  const registerRoute = (webServer) => {
    if (!webServer || typeof webServer.register !== 'function') return false;
    ctx.effect(() =>
      webServer.register({
        kind: 'prefix',
        path: ROUTE,
        handler: handleRequest,
      }),
    );
    return true;
  };
  let registered = false;
  try {
    registered = registerRoute(typeof ctx.get === 'function' ? ctx.get('webServer') : null);
  } catch {}
  if (!registered && typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (webCtx) => {
      const ws = (webCtx && webCtx.webServer) || (typeof webCtx?.get === 'function' ? webCtx.get('webServer') : null);
      registerRoute(ws);
    });
  }
  for (const tool of buildTools()) {
    ctx.effect(() =>
      ctx.tools.register({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        output: tool.output,
        timeoutMs: 240000,
        isConcurrencySafe: () => false,
        async execute(args) {
          try {
            return await tool.execute(args || {});
          } catch (error) {
            return { ok: false, error: error?.message || String(error) };
          }
        },
      }),
    );
  }
}
