<script lang="ts">
	import type { MemoryRecord } from '$lib/api/memory';

	interface MemoryUpdateDraft {
		recordId: string;
		content: string;
		visibility: 'private' | 'shared';
		importance: number;
		tags: string[];
	}

	interface Props {
		record: MemoryRecord | null;
		enabled: boolean;
		loading?: boolean;
		onSave?: (draft: MemoryUpdateDraft) => void | Promise<boolean | void>;
	}

	let { record, enabled, loading = false, onSave }: Props = $props();

	let content = $state('');
	let tags = $state('');
	let visibility = $state<'private' | 'shared'>('private');
	let importance = $state(0.5);
	let loadedRecordId = $state<string | null>(null);

	function parseTags(raw: string): string[] {
		return raw
			.split(',')
			.map((tag) => tag.trim())
			.filter((tag) => tag.length > 0);
	}

	$effect(() => {
		if (!record) {
			loadedRecordId = null;
			content = '';
			tags = '';
			visibility = 'private';
			importance = 0.5;
			return;
		}
		if (loadedRecordId === record.id) return;
		loadedRecordId = record.id;
		content = record.content;
		tags = record.tags.join(', ');
		visibility = record.visibility;
		importance = record.importance;
	});

	async function save(): Promise<void> {
		if (!record || !enabled || loading) return;
		const normalized = content.trim();
		if (!normalized) return;
		await onSave?.({
			recordId: record.id,
			content: normalized,
			visibility,
			importance,
			tags: parseTags(tags)
		});
	}
</script>

<div class="rounded border border-border-muted bg-surface">
	<div class="border-b border-border-muted px-3 py-2 text-xs text-text-muted">Edit Memory</div>
	<div class="space-y-2 p-3 text-xs">
		{#if !record}
			<div class="rounded border border-border-muted bg-inset px-2 py-1 text-text-muted">
				Select a record to edit.
			</div>
		{:else}
			<textarea
				class="min-h-[100px] w-full rounded border border-border-muted bg-inset px-2 py-1 text-text-primary outline-none placeholder:text-text-muted"
				placeholder="Edit memory content..."
				bind:value={content}
				disabled={!enabled}
			></textarea>
			<div class="grid gap-2 sm:grid-cols-2">
				<label class="rounded border border-border-muted bg-inset px-2 py-1">
					<div class="text-[10px] uppercase tracking-wide text-text-muted">Visibility</div>
					<select class="mt-1 w-full bg-transparent text-text-primary outline-none" bind:value={visibility}>
						<option value="private">private</option>
						<option value="shared">shared</option>
					</select>
				</label>
				<label class="rounded border border-border-muted bg-inset px-2 py-1">
					<div class="text-[10px] uppercase tracking-wide text-text-muted">Importance</div>
					<input
						type="number"
						step="0.1"
						min="0"
						max="1"
						class="mt-1 w-full bg-transparent text-text-primary outline-none"
						bind:value={importance}
					/>
				</label>
			</div>
			<label class="rounded border border-border-muted bg-inset px-2 py-1">
				<div class="text-[10px] uppercase tracking-wide text-text-muted">Tags (comma-separated)</div>
				<input
					type="text"
					class="mt-1 w-full bg-transparent text-text-primary outline-none placeholder:text-text-muted"
					placeholder="ops, incident, follow-up"
					bind:value={tags}
				/>
			</label>
			<button
				type="button"
				class="w-full rounded border border-focus bg-surface-raised px-3 py-1 text-xs text-text-primary"
				onclick={() => {
					void save();
				}}
				disabled={!enabled || !record || content.trim().length === 0 || loading}
			>
				{loading ? 'Updating...' : 'Update Memory'}
			</button>
		{/if}
	</div>
</div>
