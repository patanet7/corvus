<script lang="ts">
	import { Marked } from 'marked';
	import { createHighlighter, type Highlighter, type BundledLanguage } from 'shiki';
	import DOMPurify from 'dompurify';

	interface Props {
		content: string;
		streaming?: boolean;
		shikiTheme?: string;
	}

	let { content, streaming = false, shikiTheme = 'github-dark' }: Props = $props();

	// Bind reference for the prose container (used by $effect for event delegation)
	let proseContainer: HTMLDivElement | undefined = $state(undefined);

	// --- Shiki highlighter singleton (module-level, shared across all instances) ---
	let highlighter: Highlighter | null = null;
	let highlighterPromise: Promise<Highlighter> | null = null;
	const loadedLanguages = new Set<string>(['javascript', 'typescript', 'python', 'bash', 'json', 'html', 'css', 'yaml', 'markdown', 'shell', 'text', 'plaintext']);

	// Common language aliases
	const LANG_ALIASES: Record<string, string> = {
		js: 'javascript',
		ts: 'typescript',
		py: 'python',
		sh: 'bash',
		zsh: 'bash',
		yml: 'yaml',
		md: 'markdown',
		txt: 'text',
		plain: 'plaintext'
	};

	function normalizeLang(lang: string): string {
		const lower = lang.toLowerCase().trim();
		return LANG_ALIASES[lower] ?? lower;
	}

	async function getHighlighter(): Promise<Highlighter> {
		if (highlighter) return highlighter;
		if (!highlighterPromise) {
			highlighterPromise = createHighlighter({
				themes: ['github-dark', 'vitesse-dark', 'catppuccin-mocha'],
				langs: ['javascript', 'typescript', 'python', 'bash', 'json', 'html', 'css', 'yaml', 'markdown', 'shell']
			}).then((hl) => {
				highlighter = hl;
				return hl;
			});
		}
		return highlighterPromise;
	}

	async function ensureLanguageLoaded(hl: Highlighter, lang: string): Promise<string> {
		const normalized = normalizeLang(lang);
		if (loadedLanguages.has(normalized)) return normalized;
		try {
			await hl.loadLanguage(normalized as BundledLanguage);
			loadedLanguages.add(normalized);
			return normalized;
		} catch {
			// Language not available, fall back to plaintext
			return 'text';
		}
	}

	// --- Streaming code fence buffering ---
	function bufferStreamingContent(raw: string): string {
		if (!streaming) return raw;

		// Count opening and closing triple-backtick fences
		const fencePattern = /^```/gm;
		const fences = raw.match(fencePattern);
		if (!fences) return raw;

		// If odd number of fences, the last code block is incomplete
		if (fences.length % 2 !== 0) {
			const lastFenceIdx = raw.lastIndexOf('```');
			const beforeFence = raw.slice(0, lastFenceIdx);
			return beforeFence + '\n\n*[code block loading...]*\n';
		}

		return raw;
	}

	// --- DOMPurify configuration ---
	// Allow <button> for copy buttons and <span> for Shiki highlighting
	const SANITIZE_CONFIG = {
		ADD_TAGS: ['span', 'button'],
		ADD_ATTR: ['style', 'class', 'type']
	};

	// --- Marked setup with Shiki ---
	const markedInstance = new Marked();
	let renderedHtml = $state('');
	let renderVersion = $state(0);

	// Override the code renderer to use a placeholder that we replace with Shiki output
	markedInstance.use({
		renderer: {
			code({ text, lang }: { text: string; lang?: string | undefined }) {
				const langLabel = lang ? normalizeLang(lang) : 'text';
				const escapedCode = escapeHtml(text);
				// Use a data attribute so we can identify code blocks for Shiki highlighting
				// The copy button is wired up via event delegation in the $effect below
				return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-block-lang">${escapeHtml(langLabel)}</span><button class="code-block-copy" type="button">Copy</button></div><pre class="shiki-pending" data-lang="${escapeHtml(langLabel)}"><code>${escapedCode}</code></pre></div>`;
			}
		}
	});

	function escapeHtml(str: string): string {
		return str
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');
	}

	// Render markdown whenever content changes
	$effect(() => {
		const buffered = bufferStreamingContent(content);
		const currentVersion = ++renderVersion;

		// Synchronous markdown parse
		const html = markedInstance.parse(buffered, { async: false }) as string;

		// Sanitize and set initial HTML (code blocks will be plain text)
		renderedHtml = DOMPurify.sanitize(html, SANITIZE_CONFIG);

		// Async: highlight code blocks with Shiki
		highlightCodeBlocks(html, currentVersion);
	});

	async function highlightCodeBlocks(html: string, version: number) {
		// Find all shiki-pending blocks
		const pendingPattern = /<pre class="shiki-pending" data-lang="([^"]*?)"><code>([\s\S]*?)<\/code><\/pre>/g;
		const matches = [...html.matchAll(pendingPattern)];

		if (matches.length === 0) return;

		const hl = await getHighlighter();
		let result = html;

		for (const match of matches) {
			const lang = match[1] ?? 'text';
			const rawCode = match[2] ?? '';

			// Unescape HTML entities to get original code
			const code = rawCode
				.replace(/&amp;/g, '&')
				.replace(/&lt;/g, '<')
				.replace(/&gt;/g, '>')
				.replace(/&quot;/g, '"');

			const resolvedLang = await ensureLanguageLoaded(hl, lang);

			try {
				const highlighted = hl.codeToHtml(code, {
					lang: resolvedLang,
					theme: shikiTheme as 'github-dark' | 'vitesse-dark' | 'catppuccin-mocha'
				});
				result = result.replace(match[0], highlighted);
			} catch {
				// Keep the plain text fallback
			}
		}

		// Only apply if this is still the latest render
		if (version === renderVersion) {
			renderedHtml = DOMPurify.sanitize(result, SANITIZE_CONFIG);
		}
	}

	// --- Copy button event delegation ---
	// Attach click handlers to .code-block-copy buttons inside {@html} content.
	// Uses event delegation on the prose container since {@html} elements cannot
	// use Svelte event bindings directly.
	$effect(() => {
		// Subscribe to renderedHtml so this re-runs when content changes
		void renderedHtml;

		const container = proseContainer;
		if (!container) return;

		// Use a microtask to ensure the DOM has been updated with renderedHtml
		const timeoutId = setTimeout(() => {
			attachCopyHandlers(container);
		}, 0);

		return () => {
			clearTimeout(timeoutId);
			cleanupCopyHandlers(container);
		};
	});

	// Track active listeners for cleanup
	const listenerMap = new WeakMap<HTMLButtonElement, EventListener>();

	function attachCopyHandlers(container: HTMLDivElement): void {
		const buttons = container.querySelectorAll<HTMLButtonElement>('.code-block-copy');

		for (const button of buttons) {
			// Skip if already wired up
			if (listenerMap.has(button)) continue;

			const handler: EventListener = async () => {
				// Find the sibling <pre> element within the same wrapper
				const wrapper = button.closest('.code-block-wrapper');
				if (!wrapper) return;

				const preElement = wrapper.querySelector('pre');
				if (!preElement) return;

				const codeText = preElement.textContent ?? '';

				try {
					await navigator.clipboard.writeText(codeText);
					button.textContent = 'Copied!';
					setTimeout(() => {
						button.textContent = 'Copy';
					}, 2000);
				} catch {
					// Fallback: indicate failure if clipboard API unavailable
					button.textContent = 'Failed';
					setTimeout(() => {
						button.textContent = 'Copy';
					}, 2000);
				}
			};

			button.addEventListener('click', handler);
			listenerMap.set(button, handler);
		}
	}

	function cleanupCopyHandlers(container: HTMLDivElement): void {
		const buttons = container.querySelectorAll<HTMLButtonElement>('.code-block-copy');

		for (const button of buttons) {
			const handler = listenerMap.get(button);
			if (handler) {
				button.removeEventListener('click', handler);
				listenerMap.delete(button);
			}
		}
	}
</script>

<div class="prose-content" bind:this={proseContainer}>
	{@html renderedHtml}
</div>

<style>
	/* Prose typography for markdown content */
	.prose-content {
		font-size: 14px;
		line-height: 1.7;
		color: var(--color-text-primary);
		word-wrap: break-word;
		overflow-wrap: break-word;
	}

	/* Headings */
	.prose-content :global(h1) {
		font-size: 1.5em;
		font-weight: 600;
		margin: 1em 0 0.5em;
		color: var(--color-text-primary);
		border-bottom: 1px solid var(--color-border-muted);
		padding-bottom: 0.3em;
	}

	.prose-content :global(h2) {
		font-size: 1.3em;
		font-weight: 600;
		margin: 1em 0 0.5em;
		color: var(--color-text-primary);
	}

	.prose-content :global(h3) {
		font-size: 1.1em;
		font-weight: 600;
		margin: 0.8em 0 0.4em;
		color: var(--color-text-primary);
	}

	.prose-content :global(h4),
	.prose-content :global(h5),
	.prose-content :global(h6) {
		font-size: 1em;
		font-weight: 600;
		margin: 0.6em 0 0.3em;
		color: var(--color-text-secondary);
	}

	/* Paragraphs */
	.prose-content :global(p) {
		margin: 0.5em 0;
	}

	/* Links */
	.prose-content :global(a) {
		color: var(--color-text-link);
		text-decoration: none;
	}

	.prose-content :global(a:hover) {
		text-decoration: underline;
	}

	/* Bold and italic */
	.prose-content :global(strong) {
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.prose-content :global(em) {
		font-style: italic;
	}

	/* Inline code */
	.prose-content :global(code) {
		font-family: var(--font-mono);
		font-size: 0.85em;
		background: var(--color-surface-raised);
		padding: 0.15em 0.4em;
		border-radius: var(--radius-default);
		color: var(--color-text-primary);
	}

	/* Code blocks (pre > code) reset inline code styles */
	.prose-content :global(pre code) {
		background: none;
		padding: 0;
		border-radius: 0;
		font-size: 0.85em;
	}

	/* Code block wrapper */
	.prose-content :global(.code-block-wrapper) {
		position: relative;
		margin: 0.75em 0;
		border-radius: var(--radius-md);
		overflow: hidden;
		border: 1px solid var(--color-border-muted);
	}

	/* Code block header with language label and copy button */
	.prose-content :global(.code-block-header) {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.375rem 0.75rem;
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border-muted);
		font-family: var(--font-mono);
		font-size: 0.75rem;
	}

	.prose-content :global(.code-block-lang) {
		font-family: var(--font-mono);
		font-size: 0.6875rem;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	/* Copy button inside code block header */
	.prose-content :global(.code-block-copy) {
		color: var(--color-text-muted);
		background: transparent;
		border: 1px solid var(--color-border-muted);
		border-radius: var(--radius-sm, 2px);
		padding: 1px 8px;
		font-family: var(--font-mono);
		font-size: 0.6875rem;
		cursor: pointer;
		transition: color var(--duration-fast), border-color var(--duration-fast);
		line-height: 1.4;
	}

	.prose-content :global(.code-block-copy:hover) {
		color: var(--color-text-primary);
		border-color: var(--color-border);
	}

	/* Pre blocks (both pending and Shiki-rendered) */
	.prose-content :global(pre) {
		margin: 0;
		padding: 12px 16px;
		overflow-x: auto;
		font-family: var(--font-mono);
		font-size: 13px;
		line-height: 1.5;
		background: var(--color-inset);
	}

	/* When pre is inside a wrapper with header, remove top border-radius */
	.prose-content :global(.code-block-wrapper pre) {
		border-top-left-radius: 0;
		border-top-right-radius: 0;
		margin: 0;
	}

	/* Shiki generates its own pre with background; override to match our theme */
	.prose-content :global(.shiki) {
		background: var(--color-inset) !important;
		margin: 0;
		padding: 12px 16px;
		overflow-x: auto;
	}

	/* Lists */
	.prose-content :global(ul) {
		list-style: disc;
		padding-left: 1.5em;
		margin: 0.5em 0;
	}

	.prose-content :global(ol) {
		list-style: decimal;
		padding-left: 1.5em;
		margin: 0.5em 0;
	}

	.prose-content :global(li) {
		margin: 0.25em 0;
	}

	.prose-content :global(li > ul),
	.prose-content :global(li > ol) {
		margin: 0.15em 0;
	}

	/* Blockquotes */
	.prose-content :global(blockquote) {
		border-left: 3px solid var(--color-border);
		margin: 0.5em 0;
		padding: 0.25em 1em;
		color: var(--color-text-secondary);
	}

	/* Tables */
	.prose-content :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: 0.75em 0;
		font-size: 13px;
	}

	.prose-content :global(th) {
		background: var(--color-surface);
		font-weight: 600;
		text-align: left;
		padding: 6px 12px;
		border: 1px solid var(--color-border-muted);
	}

	.prose-content :global(td) {
		padding: 6px 12px;
		border: 1px solid var(--color-border-muted);
	}

	.prose-content :global(tr:nth-child(even)) {
		background: var(--color-surface-raised);
	}

	/* Horizontal rules */
	.prose-content :global(hr) {
		border: none;
		border-top: 1px solid var(--color-border-muted);
		margin: 1em 0;
	}

	/* Images */
	.prose-content :global(img) {
		max-width: 100%;
		border-radius: var(--radius-md);
		margin: 0.5em 0;
	}

	/* Task lists (checkboxes) */
	.prose-content :global(input[type='checkbox']) {
		margin-right: 0.4em;
	}
</style>
