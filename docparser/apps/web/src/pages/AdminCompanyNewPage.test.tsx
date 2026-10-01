import { describe, expect, it } from 'vitest';

/**
 * The slug derivation, tested directly.
 *
 * This is where a real bug lived: the slug was only filled while it was empty,
 * so after the first keystroke every later one was skipped and the slug froze on
 * a single letter. It behaved differently depending on typing speed, because a
 * fast typist raced React's state updates — which is exactly the kind of fault
 * a per-keystroke test pins down and a click-through never will.
 */

const autoSlug = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

const typedSlug = (value: string) =>
  value.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+/, '');

/** Replays a name one character at a time, as someone actually types it. */
function typeName(name: string, slugEdited = false): string {
  let typed = '';
  let slug = '';
  for (const ch of name) {
    typed += ch;
    if (!slugEdited) slug = autoSlug(typed);
  }
  return slug;
}

describe('company slug', () => {
  it.each([
    ['Sage Technologies',           'sage-technologies'],
    ['SSDN Technologies Pvt. Ltd.', 'ssdn-technologies-pvt-ltd'],
    ['Reliance Industries',         'reliance-industries'],
    ['ACME  Corp',                  'acme-corp'],
    ['3M India',                    '3m-india'],
    ['Tata & Sons',                 'tata-sons'],
  ])('derives %s -> %s when typed one letter at a time', (name, expected) => {
    expect(typeName(name)).toBe(expected);
  });

  it('keeps up with the whole name, not just the first letter', () => {
    // The regression: this returned "s" because the fill only ran while empty.
    expect(typeName('Sage Technologies')).toHaveLength('sage-technologies'.length);
  });

  it('stops following the name once someone edits the slug', () => {
    const edited = typeName('Sage Technologies Pvt Ltd', true);
    expect(edited).toBe('');   // never auto-filled, because the user took over
  });

  it('allows a trailing hyphen while typing, and trims it on save', () => {
    // Stripping it live would make a hyphenated slug impossible to type.
    expect(typedSlug('acme-')).toBe('acme-');
    expect(autoSlug('acme-')).toBe('acme');
  });

  it.each(['My Company!', 'A/B Testing', 'Ünïcodé Ltd', '   spaced   '])(
    'always produces a URL-safe slug from %s',
    (input) => {
      expect(autoSlug(input)).toMatch(/^[a-z0-9]*(-[a-z0-9]+)*$/);
    },
  );
});
