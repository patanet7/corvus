<script lang="ts">
	import type { DraftAttachment } from '$lib/types';

	interface Props {
		attachments: DraftAttachment[];
		onVoiceClick: () => void;
		onImagePickClick: () => void;
		onAudioPickClick: () => void;
		onFilePickClick: () => void;
		onRemoveAttachment: (attachmentId: string) => void;
	}

	let {
		attachments,
		onVoiceClick,
		onImagePickClick,
		onAudioPickClick,
		onFilePickClick,
		onRemoveAttachment
	}: Props = $props();

	function kindLabel(kind: DraftAttachment['kind']): string {
		if (kind === 'image') return 'IMG';
		if (kind === 'audio') return 'AUD';
		return 'FILE';
	}

	function formatSize(sizeBytes: number): string {
		if (sizeBytes < 1024) return `${sizeBytes}B`;
		if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)}KB`;
		return `${(sizeBytes / (1024 * 1024)).toFixed(1)}MB`;
	}
</script>

<div class="mb-2 space-y-1" aria-label="Composer capabilities">
	<div class="flex flex-wrap items-center gap-1 text-[10px] uppercase tracking-wide text-text-muted">
		<span class="rounded border border-border-muted px-1 py-0.5">Capabilities</span>
		<button
			type="button"
			class="rounded border border-border-muted px-1.5 py-0.5 transition-colors text-text-secondary hover:text-text-primary hover:border-border"
			onclick={onVoiceClick}
		>
			Voice
		</button>
		<button
			type="button"
			class="rounded border border-border-muted px-1.5 py-0.5 transition-colors text-text-secondary hover:text-text-primary hover:border-border"
			onclick={onImagePickClick}
		>
			Image
		</button>
		<button
			type="button"
			class="rounded border border-border-muted px-1.5 py-0.5 transition-colors text-text-secondary hover:text-text-primary hover:border-border"
			onclick={onAudioPickClick}
		>
			Audio
		</button>
		<button
			type="button"
			class="rounded border border-border-muted px-1.5 py-0.5 transition-colors text-text-secondary hover:text-text-primary hover:border-border"
			onclick={onFilePickClick}
		>
			File
		</button>
		<span class="rounded border border-warning px-1.5 py-0.5 text-warning">staged</span>
	</div>

	{#if attachments.length > 0}
		<div class="flex flex-wrap gap-1" aria-label="Staged attachments">
			{#each attachments as attachment (attachment.id)}
				<span
					class="inline-flex items-center gap-1 rounded-full border border-border bg-surface-raised px-2 py-0.5 text-[11px] text-text-secondary"
					title={attachment.name}
				>
					<span class="rounded border border-border-muted px-1 text-[9px] text-text-muted">
						{kindLabel(attachment.kind)}
					</span>
					<span class="max-w-36 truncate">{attachment.name}</span>
					<span class="text-text-muted">{formatSize(attachment.sizeBytes)}</span>
					<button
						type="button"
						class="text-text-muted transition-colors hover:text-text-primary"
						onclick={() => onRemoveAttachment(attachment.id)}
						aria-label={`Remove ${attachment.name}`}
					>
						x
					</button>
				</span>
			{/each}
		</div>
	{/if}
</div>
