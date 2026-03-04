<script lang="ts">
	import type { ModelInfo } from '$lib/types';

	interface Props {
		models: ModelInfo[];
		selectedModel: string;
		modeLabel?: string;
		onModelChange: (modelId: string) => void;
	}

	let { models, selectedModel, modeLabel = 'Preferred', onModelChange }: Props = $props();
	let open = $state(false);
	let openUp = $state(false);
	let trigger: HTMLButtonElement | undefined = $state(undefined);
	let searchInput: HTMLInputElement | undefined = $state(undefined);
	let searchQuery = $state('');
	let activeIndex = $state(0);

	function selectModel(id: string) {
		onModelChange(id);
		open = false;
		searchQuery = '';
		activeIndex = 0;
	}

	interface MenuItem {
		id: string;
		label: string;
		description?: string;
		backend?: string;
		available: boolean;
		isDefault?: boolean;
		isPreferred?: boolean;
		supportsTools?: boolean;
		supportsStreaming?: boolean;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;
		if (e.key === 'Escape') {
			open = false;
			return;
		}
		if (menuItems.length === 0) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			activeIndex = (activeIndex + 1) % menuItems.length;
			return;
		}
		if (e.key === 'ArrowUp') {
			e.preventDefault();
			activeIndex = (activeIndex - 1 + menuItems.length) % menuItems.length;
			return;
		}
		if (e.key === 'Enter') {
			e.preventDefault();
			selectModel(menuItems[activeIndex]?.id ?? '__preferred__');
		}
	}

	const currentModel = $derived(models.find((m) => m.id === selectedModel) ?? models[0]);
	const normalizedQuery = $derived(searchQuery.trim().toLowerCase());

	const filteredModels = $derived.by(() => {
		if (!normalizedQuery) return models;
		return models.filter((m) => {
			const hay = `${m.label} ${m.id} ${m.backend} ${m.description ?? ''}`.toLowerCase();
			return hay.includes(normalizedQuery);
		});
	});

	const backendGroups = $derived.by(() => {
		const groups = new Map<string, ModelInfo[]>();
		for (const model of filteredModels) {
			const existing = groups.get(model.backend) ?? [];
			existing.push(model);
			groups.set(model.backend, existing);
		}
		return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
	});

	const menuItems = $derived.by<MenuItem[]>(() => {
		const items: MenuItem[] = [
			{
				id: '__preferred__',
				label: 'Preferred (Auto)',
				description: 'Use agent preferred model',
				available: true,
				isPreferred: true
			}
		];
		for (const [, groupModels] of backendGroups) {
			for (const m of groupModels) {
				items.push({
					id: m.id,
					label: m.label,
					description: m.description,
					backend: m.backend,
					available: m.available,
					isDefault: m.isDefault,
					supportsTools: m.capabilities?.supports_tools,
					supportsStreaming: m.capabilities?.supports_streaming
				});
			}
		}
		return items;
	});

	function toggleMenu(): void {
		if (!open) {
			if (trigger) {
				const rect = trigger.getBoundingClientRect();
				// Prefer opening upward when close to viewport bottom.
				openUp = rect.bottom > window.innerHeight - 260;
			} else {
				openUp = true;
			}
			searchQuery = '';
			activeIndex = 0;
			requestAnimationFrame(() => searchInput?.focus());
		}
		open = !open;
	}

	$effect(() => {
		if (activeIndex >= menuItems.length) {
			activeIndex = 0;
		}
	});
</script>

<svelte:window onkeydown={open ? handleKeydown : undefined} />

{#if models.length > 0}
	<div class="relative">
		<button
			bind:this={trigger}
			class="flex items-center gap-2 px-2 py-0.5 rounded text-xs
				bg-surface-raised border border-border-muted hover:border-border
				text-text-secondary hover:text-text-primary transition-colors
				focus:outline-none focus:ring-2 focus:ring-focus"
			onclick={toggleMenu}
			aria-haspopup="listbox"
			aria-expanded={open}
		>
			<span class="font-medium">{currentModel?.label ?? selectedModel}</span>
			<span class="rounded border border-border-muted px-1 py-px text-[10px] uppercase tracking-wide">
				{modeLabel}
			</span>
			<svg class="w-3 h-3 opacity-50" viewBox="0 0 12 12" fill="none">
				<path
					d="M3 5l3 3 3-3"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
				/>
			</svg>
		</button>

		{#if open}
			<!-- Backdrop -->
			<button
				class="fixed inset-0 z-20"
				onclick={() => (open = false)}
				aria-label="Close model selector"
				tabindex="-1"
			></button>

			<!-- Dropdown -->
			<div
				class="absolute left-0 z-30 w-72 rounded-lg border border-border bg-surface shadow-lg overflow-hidden"
				style={openUp ? 'bottom: calc(100% + 0.25rem);' : 'top: calc(100% + 0.25rem);'}
				role="listbox"
				aria-label="Select model"
			>
				<div class="border-b border-border-muted p-2">
					<input
						bind:this={searchInput}
						type="text"
						class="w-full rounded border border-border bg-inset px-2 py-1 text-xs text-text-primary focus:outline-none focus:ring-2 focus:ring-focus"
						placeholder="Search models..."
						bind:value={searchQuery}
					/>
				</div>
				<div class="max-h-72 overflow-y-auto py-1">
					<button
						class="w-full text-left px-3 py-2 text-xs transition-colors focus:outline-none
							{selectedModel === '' || modeLabel === 'Preferred'
							? 'bg-surface-raised text-text-primary'
							: 'text-text-secondary hover:bg-surface-raised'}
							{activeIndex === 0 ? 'ring-1 ring-focus' : ''}"
						role="option"
						aria-selected={selectedModel === '' || modeLabel === 'Preferred'}
						onclick={() => selectModel('__preferred__')}
					>
						<div class="font-medium">Preferred (Auto)</div>
						<div class="text-text-muted text-[10px]">Use agent preferred model</div>
					</button>
					{#if filteredModels.length === 0}
						<div class="px-3 py-2 text-xs text-text-muted">No matching models.</div>
					{:else}
						{#each backendGroups as [backend, backendModels]}
							<div class="px-3 pb-1 pt-2 text-[10px] uppercase tracking-wide text-text-muted">
								{backend}
							</div>
							{#each backendModels as model}
								{@const itemIndex = menuItems.findIndex((item) => item.id === model.id)}
								<button
									class="w-full text-left px-3 py-2 text-xs transition-colors focus:outline-none
										{model.id === selectedModel && modeLabel !== 'Preferred'
										? 'bg-surface-raised text-text-primary'
										: 'text-text-secondary hover:bg-surface-raised'}
										{activeIndex === itemIndex ? 'ring-1 ring-focus' : ''}"
									role="option"
									aria-selected={model.id === selectedModel && modeLabel !== 'Preferred'}
									onclick={() => selectModel(model.id)}
								>
									<div class="flex items-center gap-2">
										<span class="font-medium">{model.label}</span>
										<span
											class="rounded border px-1 py-px text-[9px]
												{model.available ? 'border-success text-success' : 'border-error text-error'}"
										>
											{model.available ? 'available' : 'offline'}
										</span>
										{#if model.isDefault}
											<span class="text-text-muted text-[10px]">(default)</span>
										{/if}
										{#if model.capabilities?.supports_tools === false}
											<span
												class="rounded border px-1 py-px text-[9px]"
												style="border-color: color-mix(in srgb, var(--color-warning) 60%, transparent); color: var(--color-warning);"
												title="Chat-only model in current runtime (tools disabled)"
											>
												chat-only
											</span>
										{/if}
									</div>
									{#if model.description}
										<div class="text-text-muted text-[10px]">{model.description}</div>
									{/if}
								</button>
							{/each}
						{/each}
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}
