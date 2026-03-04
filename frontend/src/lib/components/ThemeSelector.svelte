<script lang="ts">
	import { listThemes } from '$lib/themes/registry';
	import { getThemeContext } from '$lib/themes/context';
	import type { ThemeConfig } from '$lib/themes/types';

	const ctx = getThemeContext();
	// Reactive: picks up runtime registerTheme() calls
	const themes = $derived(listThemes());

	// Access ctx.theme via getter to stay reactive when theme changes
	const activeId = $derived(ctx.theme.id);

	function getThemeDescription(t: ThemeConfig): string {
		const fontName = t.fonts.sans.family;
		const radius = t.details.borderRadius;
		return `${fontName} · ${radius} radius`;
	}
</script>

<div class="flex-1 overflow-y-auto p-6">
	<div class="max-w-[600px] mx-auto">
		<h2
			class="text-lg font-semibold text-text-primary mb-6"
			style="font-family: var(--font-display);"
		>
			Settings
		</h2>

		<section class="mb-8">
			<h3 class="text-sm font-medium text-text-secondary uppercase tracking-wider mb-3">
				Appearance
			</h3>

			<div class="space-y-2">
				{#each themes as t (t.id)}
					<button
						class="w-full text-left px-4 py-3 rounded-lg border transition-colors
							focus:outline-none focus:ring-2 focus:ring-focus
							{t.id === activeId
							? 'bg-surface-raised border-focus'
							: 'bg-surface border-border-muted hover:border-border hover:bg-surface-raised'}"
						onclick={() => ctx.setTheme(t.id)}
					>
						<div class="flex items-center gap-3">
							<!-- Color preview swatches -->
							<div class="flex gap-1">
								<div
									class="w-3 h-3 rounded-full"
									style="background: {t.colors.canvas}; border: 1px solid {t.colors
										.border};"
								></div>
								<div
									class="w-3 h-3 rounded-full"
									style="background: {t.colors.focus};"
								></div>
								<div
									class="w-3 h-3 rounded-full"
									style="background: {t.colors.agents.homelab};"
								></div>
							</div>
							<div class="flex-1">
								<div class="text-sm font-medium text-text-primary">{t.name}</div>
								<div class="text-xs text-text-muted">{getThemeDescription(t)}</div>
							</div>
							{#if t.id === activeId}
								<span class="text-xs text-focus font-medium">Active</span>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</section>
	</div>
</div>
