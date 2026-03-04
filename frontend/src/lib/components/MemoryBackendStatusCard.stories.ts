import type { Meta, StoryObj } from '@storybook/sveltekit';
import MemoryBackendStatusCard from './MemoryBackendStatusCard.svelte';

const meta = {
	title: 'Workspace/MemoryBackendStatusCard',
	component: MemoryBackendStatusCard,
	tags: ['autodocs']
} satisfies Meta<typeof MemoryBackendStatusCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Healthy: Story = {
	args: {
		loading: false,
		status: {
			primary: {
				name: 'fts5-primary',
				status: 'healthy',
				detail: null
			},
			overlays: [
				{
					name: 'cognee-overlay',
					status: 'healthy',
					detail: null,
					consecutiveFailures: 0
				}
			],
			configuredOverlays: [
				{
					name: 'cognee',
					enabled: true,
					weight: 0.35,
					settings: {
						data_dir: '/data/cognee'
					}
				}
			]
		}
	}
};

export const Degraded: Story = {
	args: {
		loading: false,
		status: {
			primary: {
				name: 'fts5-primary',
				status: 'healthy',
				detail: null
			},
			overlays: [
				{
					name: 'cognee-overlay',
					status: 'unhealthy',
					detail: 'cognee package not installed',
					consecutiveFailures: 2
				}
			],
			configuredOverlays: [
				{
					name: 'cognee',
					enabled: true,
					weight: 0.35,
					settings: {
						data_dir: '/data/cognee'
					}
				}
			]
		}
	}
};
