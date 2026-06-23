import { useEffect, useState } from 'react';
import { useAppState } from '@/state/AppState';
import { useDebounce } from '@/hooks/useDebounce';
import { hourLabel, isPeak, timePeriod } from '@/utils/format';

/**
 * Hour control: dropdown + slider. The slider value is debounced before it
 * commits to global state so dragging doesn't fire a request per pixel.
 */
export function TimeControls() {
  const { hour, setHour } = useAppState();
  const [local, setLocal] = useState(hour);
  const debounced = useDebounce(local, 250);

  useEffect(() => {
    if (debounced !== hour) setHour(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  useEffect(() => setLocal(hour), [hour]);

  return (
    <div className="time-controls">
      <div className="time-selector">
        <label htmlFor="hourSelect">Hour</label>
        <select id="hourSelect" value={local} onChange={(e) => setLocal(+e.target.value)}>
          {Array.from({ length: 24 }).map((_, h) => (
            <option key={h} value={h}>
              {hourLabel(h)} {isPeak(h) ? '●' : ''}
            </option>
          ))}
        </select>
      </div>
      <div className="time-slider-wrap">
        <input
          type="range"
          min={0}
          max={23}
          value={local}
          onChange={(e) => setLocal(+e.target.value)}
          className="time-slider"
          aria-label="Hour slider"
        />
        <span className={`time-period ${isPeak(local) ? 'peak' : ''}`}>{timePeriod(local)}</span>
      </div>
      {local >= 16 && (
        <div className="time-cliff-note" role="note">
          Evening — limited data, showing all-day
        </div>
      )}
    </div>
  );
}
