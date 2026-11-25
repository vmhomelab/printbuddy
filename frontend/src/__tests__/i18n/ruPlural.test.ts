import { describe, expect, it } from 'vitest';
import i18n from 'i18next';
import ru from '../../i18n/locales/ru';

describe('ru plural forms', () => {
  it('uses one/few/many by count', async () => {
    const inst = i18n.createInstance();
    await inst.init({ lng: 'ru', resources: { ru: { translation: ru } } });
    const t = (n: number) => inst.t('forecast.spoolCount', { count: n });
    expect(t(1)).toBe('1 катушка');
    expect(t(3)).toBe('3 катушки');
    expect(t(5)).toBe('5 катушек');
    expect(t(21)).toBe('21 катушка');
  });
});
