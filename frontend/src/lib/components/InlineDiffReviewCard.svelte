<script lang="ts">
	interface Hunk {
		header: string;
		lines: string[];
	}

	interface Props {
		filePath: string;
		hunks: Hunk[];
		onApprove?: () => void;
		onReject?: () => void;
		onComment?: () => void;
	}

	let { filePath, hunks, onApprove, onReject, onComment }: Props = $props();
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<div class="flex items-center justify-between gap-2">
		<p class="truncate font-mono text-xs text-text-primary">{filePath}</p>
		<div class="flex items-center gap-1">
			{#if onComment}
				<button
					type="button"
					class="rounded border border-border-muted px-2 py-0.5 text-[10px] text-text-secondary"
					onclick={onComment}
				>
					Comment
				</button>
			{/if}
			{#if onApprove}
				<button
					type="button"
					class="rounded border border-success/50 px-2 py-0.5 text-[10px] text-success"
					onclick={onApprove}
				>
					Approve
				</button>
			{/if}
			{#if onReject}
				<button
					type="button"
					class="rounded border border-error/50 px-2 py-0.5 text-[10px] text-error"
					onclick={onReject}
				>
					Reject
				</button>
			{/if}
		</div>
	</div>

	{#if hunks.length === 0}
		<p class="mt-2 text-xs text-text-muted">No hunks in this diff.</p>
	{:else}
		<div class="mt-2 space-y-2">
			{#each hunks as hunk, idx (`${filePath}-${idx}`)}
				<div class="rounded border border-border-muted bg-inset px-2 py-2">
					<p class="font-mono text-[10px] text-text-muted">{hunk.header}</p>
					<div class="mt-1 space-y-0.5 font-mono text-[10px]">
						{#each hunk.lines as line, lineIdx (`${filePath}-${idx}-${lineIdx}`)}
							<p class={line.startsWith('+') ? 'text-success' : line.startsWith('-') ? 'text-error' : 'text-text-secondary'}>
								{line}
							</p>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
