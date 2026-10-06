/** The reasons a reply can be asked for again: the API's `regenerate.Reason`, with what a screen
 * calls each one and how it explains it. The order is the sheet's order. */

export interface Reason {
	value: string;
	label: string;
	describe: string;
}

export const REASONS: Reason[] = [
	{ value: 'none', label: 'No reason', describe: 'ask for another reply without saying why' },
	{ value: 'steer', label: 'Guide the reply', describe: 'write it differently; say how below' },
	{
		value: 'bad-memory',
		label: 'Bad memory',
		describe: 'it contradicted something established earlier'
	},
	{
		value: 'looping',
		label: 'Looping',
		describe: 'it repeated itself, or the scene stopped moving'
	},
	{
		value: 'acting-for-user',
		label: 'Writing my actions',
		describe: 'it wrote your actions or words for you'
	},
	{ value: 'too-short', label: 'Too short', describe: 'there was not enough of it' },
	{ value: 'too-long', label: 'Too long', describe: 'there was too much of it' },
	{
		value: 'wrong-format',
		label: 'Wrong format',
		describe: 'the prose, dialogue or emphasis came out wrong'
	},
	{ value: 'refusing', label: 'AI refusing', describe: 'it declined to answer' }
];
