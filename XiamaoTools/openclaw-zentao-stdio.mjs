#!/usr/bin/env node

import { FastMCP, UserError } from 'file:///Users/admin/.npm-global/lib/node_modules/mcp-zentao-bugs/node_modules/fastmcp/dist/FastMCP.js';
import { z } from 'file:///Users/admin/.npm-global/lib/node_modules/mcp-zentao-bugs/node_modules/zod/index.js';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const REQUIRED_ENVS = ['ZENTAO_BASE_URL', 'ZENTAO_ACCOUNT', 'ZENTAO_PASSWORD'];
const missingEnvs = REQUIRED_ENVS.filter((key) => !String(process.env[key] || '').trim());
if (missingEnvs.length > 0) {
  process.stderr.write(`Missing required envs: ${missingEnvs.join(', ')}\n`);
  process.exit(1);
}

const IMAGE_MIME_BY_EXT = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  bmp: 'image/bmp',
  webp: 'image/webp',
  svg: 'image/svg+xml',
};
const INLINE_IMAGE_STYLE = 'max-width:360px;max-height:520px;height:auto;';

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function textToHtml(text) {
  const normalized = String(text || '').replace(/\r\n/g, '\n').trim();
  if (!normalized) return '';
  if (/<[a-z][\s\S]*>/i.test(normalized)) return normalized;

  return normalized
    .split(/\n{2,}/)
    .map((block) => `<p>${escapeHtml(block).replace(/\n/g, '<br />')}</p>`)
    .join('');
}

class ZenTaoClient {
  constructor(baseUrl, account, password) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.apiBaseUrl = `${this.baseUrl}/api.php/v1`;
    this.account = account;
    this.password = password;
    this.token = '';
  }

  async login() {
    const response = await fetch(`${this.apiBaseUrl}/tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account: this.account,
        password: this.password,
      }),
    });
    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new Error(`Login failed ${response.status}: ${text}`);
    }
    const data = await response.json();
    if (!data?.token) {
      throw new Error('Login response missing token');
    }
    this.token = data.token;
    return this.token;
  }

  async request(path, { method = 'GET', query = {}, body, bodyType = 'json', headers: extraHeaders = {} } = {}, retry = true) {
    const normalizedPath = this.normalizePath(path);
    const url = new URL(normalizedPath, `${this.apiBaseUrl}/`);
    for (const [key, value] of Object.entries(query || {})) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }

    const headers = { ...extraHeaders };
    if (this.token) {
      headers.Token = this.token;
    }
    let requestBody = body;
    if (body !== undefined) {
      if (bodyType === 'json') {
        headers['Content-Type'] = 'application/json';
        requestBody = JSON.stringify(body);
      } else if (bodyType !== 'form') {
        throw new Error(`Unsupported bodyType: ${bodyType}`);
      }
    }

    const response = await fetch(url, {
      method,
      headers,
      body: requestBody,
    });

    if ((response.status === 401 || response.status === 403) && retry) {
      await this.login();
      return this.request(path, { method, query, body, bodyType, headers: extraHeaders }, false);
    }

    const text = await response.text();
    const payload = text ? this.tryJson(text) : null;
    if (!response.ok) {
      throw new Error(`${method} ${url.pathname} failed ${response.status}: ${typeof payload === 'string' ? payload : JSON.stringify(payload)}`);
    }
    return payload;
  }

  async requestPage(path, { method = 'GET', body, headers: extraHeaders = {} } = {}, retry = true) {
    const url = this.resolvePageUrl(path);
    const headers = { ...extraHeaders };
    if (this.token) {
      headers.Token = this.token;
      headers.Cookie = `zentaosid=${this.token}`;
    }

    const response = await fetch(url, {
      method,
      headers,
      body,
      redirect: 'manual',
    });

    if ((response.status === 401 || response.status === 403) && retry) {
      await this.login();
      return this.requestPage(path, { method, body, headers: extraHeaders }, false);
    }

    const text = await response.text();
    if (!response.ok && response.status !== 302) {
      throw new Error(`${method} ${url} failed ${response.status}: ${text}`);
    }
    return { status: response.status, text, headers: response.headers, url };
  }

  resolvePageUrl(path) {
    if (!path) return `${this.baseUrl}/`;
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    if (path.startsWith('/zentao/')) {
      return new URL(path, this.baseUrl).toString();
    }
    if (path.startsWith('/')) {
      return new URL(path.slice(1), `${this.baseUrl}/`).toString();
    }
    return new URL(path, `${this.baseUrl}/`).toString();
  }

  async getCreateBugForm(product) {
    const productId = Number(product);
    if (!Number.isFinite(productId) || productId <= 0) {
      throw new UserError(`无效 product: ${product}`);
    }

    const formPath = `/bug-create-${productId}--from=global.html`;
    const { text } = await this.requestPage(formPath);
    const formMatch = text.match(/<form[^>]*id=["']form-bug-create["'][^>]*action=["']([^"']+)["'][^>]*>/i);
    const uidMatch = text.match(/name=["']uid["'][^>]*value=["']([^"']+)["']/i);
    if (!formMatch || !uidMatch) {
      throw new Error(`无法从创建页解析 Bug 表单: ${formPath}`);
    }

    return {
      action: formMatch[1],
      uid: uidMatch[1],
      referer: this.resolvePageUrl(formPath),
    };
  }

  normalizeAssignedTo(value) {
    if (!value) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'object') return String(value.account || value.realname || '').trim();
    return String(value).trim();
  }

  normalizeOpenedBuilds(openedBuild) {
    const builds = Array.isArray(openedBuild) ? openedBuild : [openedBuild || 'trunk'];
    return builds
      .map((build) => {
        if (build && typeof build === 'object') return build.id || build.title || '';
        return build;
      })
      .map((build) => {
        if (build === undefined || build === null || build === '') return 'trunk';
        if (String(build).trim() === '主干') return 'trunk';
        return String(build).trim();
      })
      .filter(Boolean);
  }

  async uploadInlineImage(uid, imagePath) {
    const normalizedPath = String(imagePath || '').trim();
    if (!normalizedPath) throw new UserError('inlineImagePaths contains an empty path');

    let buffer;
    try {
      buffer = await readFile(normalizedPath);
    } catch {
      throw new UserError(`图片不存在或不可读: ${normalizedPath}`);
    }

    const fileName = path.basename(normalizedPath);
    const extension = path.extname(fileName).slice(1).toLowerCase();
    const mime = IMAGE_MIME_BY_EXT[extension];
    if (!mime) {
      throw new UserError(`不支持的内嵌图片格式: ${normalizedPath}`);
    }

    const form = new FormData();
    form.append('imgFile', new Blob([buffer], { type: mime }), fileName);

    const response = await this.request('/files', {
      method: 'POST',
      query: { uid },
      body: form,
      bodyType: 'form',
    });
    const imageUrl = String(response?.url || '').trim();
    if (!imageUrl) {
      throw new Error(`内嵌图片上传成功但未返回 URL: ${normalizedPath}`);
    }

    return { fileName, imageUrl };
  }

  async buildInlineImageHtml(uid, inlineImagePaths) {
    const images = [];
    for (const imagePath of inlineImagePaths) {
      const { fileName, imageUrl } = await this.uploadInlineImage(uid, imagePath);
      images.push(`<p><img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(fileName)}" style="${INLINE_IMAGE_STYLE}" /></p>`);
    }

    return images.join('');
  }

  async prepareFieldsForForm(fields, uid, inlineImagePaths = []) {
    if (!Array.isArray(inlineImagePaths) || inlineImagePaths.length === 0) return { ...fields };

    const preparedFields = { ...fields };
    const stepsHtml = textToHtml(preparedFields.steps);
    const inlineImageHtml = await this.buildInlineImageHtml(uid, inlineImagePaths);
    preparedFields.steps = `${stepsHtml}${inlineImageHtml}`;
    return preparedFields;
  }

  appendBugFields(form, fields, uid) {
    const append = (key, value) => {
      if (value === undefined || value === null || value === '') return;
      form.append(key, String(value));
    };

    append('product', fields.product);
    append('title', fields.title);
    append('project', fields.project);
    append('assignedTo', this.normalizeAssignedTo(fields.assignedTo));
    append('type', fields.type);
    append('severity', fields.severity);
    append('pri', fields.pri);
    append('module', fields.module);
    append('steps', fields.steps);
    append('os', fields.os);
    append('browser', fields.browser);
    append('hardware', fields.hardware);
    append('keywords', fields.keywords);
    append('comment', fields.comment);
    append('uid', uid);

    for (const build of this.normalizeOpenedBuilds(fields.openedBuild)) {
      append('openedBuild[]', build);
    }
  }

  async getEditBugForm(bugId) {
    const numericBugId = Number(bugId);
    if (!Number.isFinite(numericBugId) || numericBugId <= 0) {
      throw new UserError(`无效 bugId: ${bugId}`);
    }

    const formPath = `/bug-edit-${numericBugId}.html`;
    const { text } = await this.requestPage(formPath);
    const formMatch =
      text.match(/<form[^>]*id=["'][^"']*bug[^"']*["'][^>]*action=["']([^"']+)["'][^>]*>/i) ||
      text.match(/<form[^>]*action=["']([^"']+)["'][^>]*id=["'][^"']*bug[^"']*["'][^>]*>/i) ||
      text.match(/<form[^>]*action=["']([^"']+)["'][^>]*>/i);
    const uidMatch = text.match(/name=["']uid["'][^>]*value=["']([^"']+)["']/i);
    if (!formMatch || !uidMatch) {
      throw new Error(`无法从编辑页解析 Bug 表单: ${formPath}`);
    }

    return {
      action: formMatch[1],
      uid: uidMatch[1],
      referer: this.resolvePageUrl(formPath),
    };
  }

  async findRecentlyCreatedBug(fields) {
    const productId = Number(fields.product);
    if (!Number.isFinite(productId) || productId <= 0) return 0;

    const list = await this.request(`/products/${productId}/bugs`, { query: { page: 1, limit: 20 } });
    const bugs = Array.isArray(list?.bugs) ? list.bugs : [];
    const assignedTo = this.normalizeAssignedTo(fields.assignedTo);
    const project = Number(fields.project || 0);
    const match = bugs.find((bug) => {
      const bugAssigned = this.normalizeAssignedTo(bug?.assignedTo);
      return (
        String(bug?.title || '') === String(fields.title || '') &&
        Number(bug?.project || 0) === project &&
        bugAssigned === assignedTo
      );
    }) || bugs.find((bug) => String(bug?.title || '') === String(fields.title || ''));
    return Number(match?.id || 0);
  }

  extractBugFiles(payload) {
    const bug = payload?.bug || payload;
    const files = bug?.files;
    if (!files || typeof files !== 'object') return [];
    return Object.values(files);
  }

  async uploadAttachmentsToBug(bugId, attachmentPaths, fields = null) {
    const numericBugId = Number(bugId);
    if (!Number.isFinite(numericBugId) || numericBugId <= 0) {
      throw new UserError(`无效 bugId: ${bugId}`);
    }

    const currentPayload = fields ? { bug: fields } : await this.request(`/bugs/${numericBugId}`);
    const bugFields = currentPayload?.bug || currentPayload;
    const { action, uid, referer } = await this.getEditBugForm(numericBugId);

    const form = new FormData();
    this.appendBugFields(form, bugFields, uid);

    const uploadedFiles = [];
    for (const attachmentPath of attachmentPaths) {
      const normalizedPath = String(attachmentPath || '').trim();
      if (!normalizedPath) throw new UserError('attachmentPaths contains an empty path');

      let buffer;
      try {
        buffer = await readFile(normalizedPath);
      } catch (error) {
        throw new UserError(`附件不存在或不可读: ${normalizedPath}`);
      }

      const fileName = path.basename(normalizedPath);
      form.append('files[]', new Blob([buffer]), fileName);
      form.append('labels[]', fileName);
      uploadedFiles.push(fileName);
    }

    await this.requestPage(action, {
      method: 'POST',
      body: form,
      headers: {
        Referer: referer,
        'X-Requested-With': 'XMLHttpRequest',
      },
    });

    const bug = await this.request(`/bugs/${numericBugId}`);
    return { bug, uploadedFiles };
  }

  async createBugViaForm(fields, attachmentPaths = [], inlineImagePaths = []) {
    const { action, uid, referer } = await this.getCreateBugForm(fields.product);
    const preparedFields = await this.prepareFieldsForForm(fields, uid, inlineImagePaths);
    const form = new FormData();
    this.appendBugFields(form, preparedFields, uid);

    const uploadedFiles = [];
    for (const attachmentPath of attachmentPaths) {
      const normalizedPath = String(attachmentPath || '').trim();
      if (!normalizedPath) throw new UserError('attachmentPaths contains an empty path');

      let buffer;
      try {
        buffer = await readFile(normalizedPath);
      } catch (error) {
        throw new UserError(`附件不存在或不可读: ${normalizedPath}`);
      }

      const fileName = path.basename(normalizedPath);
      form.append('files[]', new Blob([buffer]), fileName);
      form.append('labels[]', fileName);
      uploadedFiles.push(fileName);
    }

    const pageResult = await this.requestPage(action, {
      method: 'POST',
      body: form,
      headers: {
        Referer: referer,
        'X-Requested-With': 'XMLHttpRequest',
      },
    });
    const payload = this.tryJson(pageResult.text);
    const location = pageResult.headers.get('location') || '';
    const loadUrl = typeof payload === 'object' && payload ? String(payload.load || payload.locate || '') : '';
    const bugIdMatch =
      loadUrl.match(/bug-view-(\d+)\.html/i) ||
      location.match(/bug-view-(\d+)\.html/i) ||
      pageResult.text.match(/bug-view-(\d+)\.html/i);
    const bugId = bugIdMatch ? Number(bugIdMatch[1]) : await this.findRecentlyCreatedBug(preparedFields);
    if (!bugId) {
      throw new Error(`Bug 表单已提交，但未能从响应中解析 bugID。status=${pageResult.status}`);
    }
    const bug = await this.request(`/bugs/${bugId}`);

    return { bug, uploadedFiles };
  }

  normalizePath(path) {
    if (!path) return '';
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    const normalized = path.replace(/^\/+/, '');
    return normalized.startsWith('api.php/') ? normalized.replace(/^api\.php\/v1\/?/, '') : normalized;
  }

  tryJson(text) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
}

const client = new ZenTaoClient(
  process.env.ZENTAO_BASE_URL,
  process.env.ZENTAO_ACCOUNT,
  process.env.ZENTAO_PASSWORD,
);

function logStderr(message) {
  process.stderr.write(`[openclaw-zentao-stdio] ${message}\n`);
}

const server = new FastMCP({
  name: 'OpenClaw ZenTao MCP',
  version: '0.1.0',
  instructions: 'ZenTao MCP over stdio for product/project lookup and bug creation.',
  roots: { enabled: false },
});

function asText(data) {
  return { content: [{ type: 'text', text: JSON.stringify(data) }] };
}

function buildBugLinks(baseUrl, bugId) {
  const normalizedBase = String(baseUrl || '').replace(/\/$/, '');
  if (!normalizedBase || !bugId) return {};
  return {
    bugUrl: `${normalizedBase}/bug-view-${bugId}.html`,
    bugAltUrl: `${normalizedBase}/index.php?m=bug&f=view&bugID=${bugId}`,
  };
}

function normalizeNeedle(value) {
  return String(value || '').trim().toLowerCase();
}

function rankMatches(items, keyword, fields) {
  if (!keyword) return items;
  const needle = keyword.toLowerCase();
  const exact = [];
  const contains = [];
  for (const item of items) {
    const values = fields.map((field) => normalizeNeedle(item?.[field]));
    if (values.some((value) => value && value === needle)) {
      exact.push(item);
      continue;
    }
    if (values.some((value) => value && value.includes(needle))) {
      contains.push(item);
    }
  }
  return [...exact, ...contains];
}

async function fetchPagedItems(path, arrayKey, pageLimit = 200, maxPages = 20) {
  const items = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const data = await client.request(path, { query: { page, limit: pageLimit } });
    const batch = Array.isArray(data?.[arrayKey]) ? data[arrayKey] : [];
    items.push(...batch);
    const total = Number(data?.total || 0);
    if (batch.length === 0 || (total > 0 && items.length >= total)) {
      break;
    }
    if (batch.length < pageLimit) {
      break;
    }
  }
  return items;
}

server.addTool({
  name: 'zentao_call',
  description: 'Generic ZenTao REST caller for api.php/v1 endpoints.',
  parameters: z.object({
    path: z.string().describe('Relative API path, for example /projects or /bugs/1'),
    method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']).optional().default('GET'),
    query: z.record(z.union([z.string(), z.number(), z.boolean()])).optional(),
    body: z.record(z.any()).optional(),
  }),
  execute: async (args) => asText(await client.request(args.path, args)),
});

server.addTool({
  name: 'search_products',
  description: 'List products and filter by product name keyword.',
  parameters: z.object({
    keyword: z.string().optional(),
    limit: z.number().optional().default(20),
  }),
  execute: async ({ keyword, limit }) => {
    const products = rankMatches(
      await fetchPagedItems('/products', 'products'),
      keyword,
      ['name', 'code'],
    )
      .slice(0, limit);
    return asText({ products });
  },
});

server.addTool({
  name: 'search_projects',
  description: 'List projects and filter by project name keyword.',
  parameters: z.object({
    keyword: z.string().optional(),
    limit: z.number().optional().default(20),
  }),
  execute: async ({ keyword, limit }) => {
    const projects = rankMatches(
      await fetchPagedItems('/projects', 'projects'),
      keyword,
      ['name', 'code'],
    )
      .slice(0, limit);
    return asText({ projects });
  },
});

server.addTool({
  name: 'search_users',
  description: 'List users and filter by realname/account keyword.',
  parameters: z.object({
    keyword: z.string().optional(),
    limit: z.number().optional().default(50),
  }),
  execute: async ({ keyword, limit }) => {
    const users = rankMatches(
      await fetchPagedItems('/users', 'users'),
      keyword,
      ['realname', 'account', 'pinyin'],
    )
      .slice(0, limit);
    return asText({ users });
  },
});

server.addTool({
  name: 'create_bug',
  description: 'Create a ZenTao bug with explicit product and optional project.',
  parameters: z.object({
    product: z.number(),
    project: z.number().optional(),
    title: z.string(),
    assignedTo: z.string().optional(),
    type: z.string().optional(),
    severity: z.number().optional(),
    pri: z.number().optional(),
    module: z.number().optional(),
    openedBuild: z.string().optional(),
    steps: z.string(),
    os: z.string().optional(),
    hardware: z.string().optional(),
    inlineImagePaths: z.array(z.string()).optional().describe('Local image file paths to embed at the end of steps as inline rich-text images.'),
    attachmentPaths: z.array(z.string()).optional().describe('Local file paths to upload as bug attachments during creation.'),
  }),
  execute: async (args) => {
    if (!args.product) throw new UserError('product is required');
    const attachmentPaths = Array.isArray(args.attachmentPaths) ? args.attachmentPaths.filter(Boolean) : [];
    const inlineImagePaths = Array.isArray(args.inlineImagePaths) ? args.inlineImagePaths.filter(Boolean) : [];
    const { attachmentPaths: _attachmentPaths, inlineImagePaths: _inlineImagePaths, ...bugArgs } = args;
    let result;
    if (attachmentPaths.length > 0 || inlineImagePaths.length > 0) {
      try {
        result = await client.createBugViaForm(bugArgs, attachmentPaths, inlineImagePaths);
        const files = client.extractBugFiles(result.bug);
        if (attachmentPaths.length > 0 && files.length === 0) {
          const bugId = Number(result?.bug?.bug?.id || result?.bug?.id || 0);
          if (!bugId) throw new Error('创建后未能获取 bugID 以执行附件补传');
          logStderr(`create_bug primary attachment strategy returned empty files for bug ${bugId}, fallback to post-create upload`);
          result = await client.uploadAttachmentsToBug(bugId, attachmentPaths, result?.bug?.bug || result?.bug);
        }
      } catch (error) {
        if (inlineImagePaths.length > 0) throw error;
        logStderr(`create_bug primary attachment strategy failed, fallback to plain create + post-create upload: ${error.message}`);
        const createdBug = await client.request('/bugs', { method: 'POST', body: bugArgs });
        const bugId = Number(createdBug?.bug?.id || createdBug?.id || 0);
        if (!bugId) throw error;
        result = await client.uploadAttachmentsToBug(bugId, attachmentPaths, createdBug?.bug || createdBug);
      }
    } else {
      result = { bug: await client.request('/bugs', { method: 'POST', body: bugArgs }), uploadedFiles: [] };
    }
    const bug = result.bug;
    return asText({
      ...bug,
      ...buildBugLinks(process.env.ZENTAO_BASE_URL, bug?.id),
      uploadedFiles: result.uploadedFiles,
    });
  },
});

server.addTool({
  name: 'get_bug_detail',
  description: 'Fetch full bug detail by bug id.',
  parameters: z.object({ bugId: z.number() }),
  execute: async ({ bugId }) => asText(await client.request(`/bugs/${bugId}`)),
});

server.addTool({
  name: 'list_product_bugs',
  description: 'List bugs under a product for post-create verification.',
  parameters: z.object({
    productId: z.number(),
    page: z.number().optional().default(1),
    limit: z.number().optional().default(100),
  }),
  execute: async ({ productId, page, limit }) =>
    asText(await client.request(`/products/${productId}/bugs`, { query: { page, limit } })),
});

server.addTool({
  name: 'list_project_bugs',
  description: 'List bugs under a project for post-create verification.',
  parameters: z.object({
    projectId: z.number(),
    page: z.number().optional().default(1),
    limit: z.number().optional().default(100),
  }),
  execute: async ({ projectId, page, limit }) =>
    asText(await client.request(`/projects/${projectId}/bugs`, { query: { page, limit } })),
});

try {
  logStderr('starting login');
  await client.login();
  logStderr('login succeeded, starting stdio transport');
  await server.start({ transportType: 'stdio' });
  logStderr('server.start returned');
} catch (error) {
  process.stderr.write(`Fatal: ${error?.stack || error?.message || error}\n`);
  process.exit(1);
}
