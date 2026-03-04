<script lang="ts">
	interface MemoryCreateDraft {
		content: string;
		visibility: 'private' | 'shared';
		importance: number;
		tags: string[];
	}

	interface Props {
		enabled: boolean;
		loading?: boolean;
		domain?: string;
		onSave?: (draft: MemoryCreateDraft) => void | Promise<boolean | void>;
	}

	let { enabled, loading = false, domain, onSave }: Props = $props();

	let content = $state('');
	let tags = $state('');
	let visibility = $state<'private' | 'shared'>('private');
	let importance = $state(0.6);

	function parseTags(raw: string): string[] {
		return raw
			.split(',')
			.map((tag) => tag.trim())
			.filter((tag) => tag.length > 0);
	}

	async function save(): Promise<void> {
		const normalized = content.trim();
		if (!normalized || !enabled || loading) return;
		const result = await onSave?.({
			content: normalized,
			visibility,
			importance,
			tags: parseTags(tags)
		});
		if (result === false) return;
		content = '';
		tags = '';
	}
</script>

<div class="rounded border border-border-muted bg-surface">
	<div class="border-b border-border-muted px-3 py-2 text-xs text-text-muted">Create Memory</div>
	<div class="space-y-2 p-3 text-xs">
		{#if !enabled}
			<div class="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-warning">
				Selected agent does not have write permission.
			</div>
		{/if}
		{#if domain}
			<div class="rounded border border-border-muted bg-inset px-2 py-1 text-[11px] text-text-muted">
				Domain override: <span class="text-text-primary">{domain}</span>
			</div>
		{/if}
		<textarea
			class="min-h-[110px] w-full rounded border border-border-muted bg-inset px-2 py-1 text-text-primary outline-none placeholder:text-text-muted"
			placeholder="Capture a memory note for the selected agent context..."
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
			disabled={!enabled || content.trim().length === 0 || loading}
		>
			{loading ? 'Saving...' : 'Save Memory'}
		</button>
	</div>
</div>
