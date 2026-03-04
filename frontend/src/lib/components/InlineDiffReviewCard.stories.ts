import type { Meta, StoryObj } from '@storybook/sveltekit';
import InlineDiffReviewCard from './InlineDiffReviewCard.svelte';

const meta = {
	title: 'Tasks/InlineDiffReviewCard',
	component: InlineDiffReviewCard,
	tags: ['autodocs'],
	args: {
		filePath: 'frontend/src/components/Nav.svelte',
		hunks: [
			{
				header: '@@ -34,3 +34,4 @@',
				lines: [
					'- const active = false;',
					'+ const active = $state(false);',
					'+ function toggle() { active = !active; }'
				]
			}
		]
	}
} satisfies Meta<typeof InlineDiffReviewCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
