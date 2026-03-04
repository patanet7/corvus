<script lang="ts">
	import type { ConfirmRequest } from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';

	interface Props {
		confirmRequest: ConfirmRequest;
		onRespond: (callId: string, approved: boolean) => void;
	}

	let { confirmRequest, onRespond }: Props = $props();
	const themeCtx = getThemeContext();

	let dialogElement: HTMLDivElement | undefined = $state(undefined);
	let previouslyFocused: HTMLElement | null = null;
	let remainingMs = $state(0);
	let responded = $state(false);

	const totalMs = $derived(confirmRequest.timeoutS * 1000);
	const createdAtMs = $derived(confirmRequest.createdAt.getTime());

	// Reset responded state when a new confirm request arrives
	$effect(() => {
		void confirmRequest.callId;
		responded = false;
	});

	// Countdown timer
	$effect(() => {
		if (responded) return;

		const total = totalMs;
		const created = createdAtMs;
		const elapsed = Date.now() - created;
		remainingMs = Math.max(0, total - elapsed);

		const interval = setInterval(() => {
			const now = Date.now();
			const newElapsed = now - created;
			remainingMs = Math.max(0, total - newElapsed);

			if (remainingMs <= 0) {
				clearInterval(interval);
				handleDeny();
			}
		}, 100);

		return () => clearInterval(interval);
	});

	const remainingSeconds = $derived(Math.ceil(remainingMs / 1000));
	const progressPct = $derived((remainingMs / totalMs) * 100);
	const urgencyStyle = $derived(themeCtx.theme.components.confirmCard.urgencyStyle);
	const countdownStyle = $derived(themeCtx.theme.components.confirmCard.countdownStyle);

	const sanitizedParams = $derived.by(() => {
		const json = JSON.stringify(confirmRequest.params, null, 2);
		if (json.length <= 300) return json;
		return json.slice(0, 300) + '...';
	});

	function handleApprove() {
		if (responded) return;
		responded = true;
		onRespond(confirmRequest.callId, true);
	}

	function handleDeny() {
		if (responded) return;
		responded = true;
		onRespond(confirmRequest.callId, false);
	}

	// Focus trap
	$effect(() => {
		if (!dialogElement) return;
		previouslyFocused = document.activeElement as HTMLElement | null;

		const focusableSelectors = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
		const focusableElements = Array.from(dialogElement.querySelectorAll<HTMLElement>(focusableSelectors));
		const denyButton = focusableElements.find(el => el.classList.contains('confirm-btn-deny'));
		if (denyButton) denyButton.focus();

		function trapFocus(e: KeyboardEvent) {
			if (e.key !== 'Tab' || focusableElements.length === 0) return;
			const first = focusableElements[0]!;
			const last = focusableElements[focusableElements.length - 1]!;
			if (e.shiftKey) {
				if (document.activeElement === first) {
					e.preventDefault();
					last.focus();
				}
			} else {
				if (document.activeElement === last) {
					e.preventDefault();
					first.focus();
				}
			}
		}

		dialogElement.addEventListener('keydown', trapFocus);
		return () => {
			dialogElement?.removeEventListener('keydown', trapFocus);
			previouslyFocused?.focus();
		};
	});

	function handleKeydown(e: KeyboardEvent) {
		if (responded) return;
		if (e.key === 'Enter') {
			// Only approve if the Approve button has focus
			const active = document.activeElement;
			if (active?.classList.contains('confirm-btn-approve')) {
				e.preventDefault();
				handleApprove();
			}
		}
		if (e.key === 'Escape') {
			e.preventDefault();
			handleDeny();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="confirm-overlay" role="dialog" aria-modal="true" aria-label="Tool approval required">
	<div class="confirm-card urgency-{urgencyStyle}" bind:this={dialogElement}>
		<!-- Header -->
		<div class="confirm-header">
			<svg class="confirm-warning-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
				<path
					d="M9 1.5L1.5 15H16.5L9 1.5Z"
					stroke="var(--color-warning)"
					stroke-width="1.5"
					stroke-linejoin="round"
					fill="none"
				/>
				<line x1="9" y1="7" x2="9" y2="10.5" stroke="var(--color-warning)" stroke-width="1.5" stroke-linecap="round" />
				<circle cx="9" cy="13" r="0.75" fill="var(--color-warning)" />
			</svg>
			<span class="confirm-title">Approval Required</span>
		</div>

		<!-- Tool info -->
		<div class="confirm-tool-info">
			<span class="confirm-label">Tool</span>
			<span class="confirm-tool-name">{confirmRequest.tool}</span>
		</div>

		<!-- Params -->
		{#if Object.keys(confirmRequest.params).length > 0}
			<div class="confirm-params">
				<span class="confirm-label">Parameters</span>
				<pre class="confirm-params-content">{sanitizedParams}</pre>
			</div>
		{/if}

		<!-- Countdown -->
		<div class="confirm-countdown">
			{#if countdownStyle === 'bar'}
				<div class="confirm-countdown-bar-track">
					<div
						class="confirm-countdown-bar-fill"
						style="width: {progressPct}%;"
						class:confirm-countdown-urgent={remainingSeconds <= 5}
					></div>
				</div>
				<span class="confirm-countdown-text">{remainingSeconds}s remaining</span>
			{:else if countdownStyle === 'ring'}
				<div class="confirm-countdown-ring-row">
					<div
						class="confirm-countdown-ring {remainingSeconds <= 5 ? 'confirm-countdown-urgent' : ''}"
						style="--progress: {progressPct}%;"
						aria-hidden="true"
					></div>
					<span class="confirm-countdown-text">{remainingSeconds}s remaining</span>
				</div>
			{:else}
				<span class="confirm-countdown-text">{remainingSeconds}s remaining</span>
			{/if}
		</div>

		<!-- Actions -->
		<div class="confirm-actions">
			<button
				class="confirm-btn confirm-btn-deny"
				onclick={handleDeny}
				disabled={responded}
			>
				Deny
			</button>
			<button
				class="confirm-btn confirm-btn-approve"
				onclick={handleApprove}
				disabled={responded}
			>
				Approve
			</button>
		</div>

		<!-- Keyboard hints -->
		<div class="confirm-hints">
			<kbd>Enter</kbd> approve (when focused) -- <kbd>Esc</kbd> deny
		</div>
	</div>
</div>

<style>
	.confirm-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: color-mix(in srgb, var(--color-canvas) 60%, transparent);
		z-index: 100;
		animation: fade-in var(--duration-fast) ease-out;
	}

	@keyframes fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.confirm-card {
		background: var(--color-surface-raised);
		border: 2px solid var(--color-warning);
		border-radius: var(--radius-lg);
		padding: 16px;
		width: 100%;
		max-width: 420px;
		margin: 0 16px;
		animation: slide-up var(--duration-normal) var(--ease-out-expo);
	}

	.confirm-card.urgency-glow {
		box-shadow:
			0 0 0 1px color-mix(in srgb, var(--color-warning) 45%, transparent),
			0 0 14px color-mix(in srgb, var(--color-warning) 26%, transparent);
	}

	.confirm-card.urgency-pulse-bg {
		animation:
			slide-up var(--duration-normal) var(--ease-out-expo),
			confirm-pulse 1.8s ease-in-out infinite;
	}

	@keyframes slide-up {
		from {
			opacity: 0;
			transform: translateY(8px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.confirm-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 12px;
	}

	.confirm-warning-icon {
		flex-shrink: 0;
	}

	.confirm-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.confirm-tool-info {
		margin-bottom: 8px;
	}

	.confirm-label {
		display: block;
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-muted);
		margin-bottom: 4px;
	}

	.confirm-tool-name {
		font-family: var(--font-mono);
		font-size: 13px;
		color: var(--color-text-primary);
	}

	.confirm-params {
		margin-bottom: 12px;
	}

	.confirm-params-content {
		font-family: var(--font-mono);
		font-size: 11px;
		line-height: 1.5;
		color: var(--color-text-secondary);
		background: var(--color-inset);
		padding: 8px;
		border-radius: var(--radius-default);
		overflow-x: auto;
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 200px;
		overflow-y: auto;
	}

	.confirm-countdown {
		margin-bottom: 12px;
	}

	.confirm-countdown-ring-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.confirm-countdown-ring {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: conic-gradient(var(--color-warning) var(--progress), var(--color-border-muted) 0);
	}

	.confirm-countdown-bar-track {
		height: 4px;
		background: var(--color-border-muted);
		border-radius: var(--radius-sm);
		overflow: hidden;
		margin-bottom: 4px;
	}

	.confirm-countdown-bar-fill {
		height: 100%;
		background: var(--color-warning);
		border-radius: var(--radius-sm);
		transition: width var(--duration-instant) linear;
	}

	.confirm-countdown-urgent {
		background: var(--color-error);
	}

	.confirm-countdown-ring.confirm-countdown-urgent {
		background: conic-gradient(var(--color-error) var(--progress), var(--color-border-muted) 0);
	}

	.confirm-countdown-text {
		font-size: 11px;
		font-family: var(--font-mono);
		color: var(--color-text-muted);
	}

	.confirm-actions {
		display: flex;
		gap: 8px;
		margin-bottom: 8px;
	}

	.confirm-btn {
		flex: 1;
		padding: 8px 16px;
		border: none;
		border-radius: var(--radius-md);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: opacity var(--duration-fast) ease;
	}

	.confirm-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.confirm-btn:not(:disabled):hover {
		opacity: 0.9;
	}

	.confirm-btn:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}

	.confirm-btn-approve {
		background: var(--color-success);
		color: var(--color-text-on-accent);
	}

	.confirm-btn-deny {
		background: var(--color-error);
		color: var(--color-text-on-accent);
	}

	.confirm-hints {
		text-align: center;
		font-size: 10px;
		color: var(--color-text-muted);
	}

	.confirm-hints kbd {
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 1px 4px;
		background: var(--color-surface);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border-muted);
	}

	@keyframes confirm-pulse {
		0%,
		100% {
			background: var(--color-surface-raised);
		}
		50% {
			background: color-mix(in srgb, var(--color-warning) 12%, var(--color-surface-raised));
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.confirm-overlay,
		.confirm-card {
			animation: none;
		}
	}
</style>
