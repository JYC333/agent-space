import { useId } from 'react'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import {
  isScheduledFrequency,
  WEEKDAY_OPTIONS,
  type ScheduleFormValue,
} from './sourcePageModel'

export function ScheduleRuleFields(props: {
  fetchFrequency: string
  value: ScheduleFormValue
  onChange: (value: ScheduleFormValue) => void
}) {
  const set = (patch: Partial<ScheduleFormValue>) => props.onChange({ ...props.value, ...patch })

  if (!isScheduledFrequency(props.fetchFrequency)) {
    return (
      <div className="space-y-1.5">
        <Label>Schedule</Label>
        <div className="flex h-9 items-center rounded-md border border-border bg-muted/30 px-3 text-sm text-muted-foreground">
          Manual only
        </div>
      </div>
    )
  }

  if (props.fetchFrequency === 'hourly') {
    return (
      <ScheduleNumberField
        label="Minute"
        value={props.value.minute}
        min={0}
        max={59}
        placeholder="0"
        onChange={minute => set({ minute })}
      />
    )
  }

  if (props.fetchFrequency === 'daily') {
    return (
      <div className="grid grid-cols-2 gap-3">
        <ScheduleNumberField
          label="Hour"
          value={props.value.hour}
          min={0}
          max={23}
          placeholder="9"
          onChange={hour => set({ hour })}
        />
        <ScheduleNumberField
          label="Minute"
          value={props.value.minute}
          min={0}
          max={59}
          placeholder="0"
          onChange={minute => set({ minute })}
        />
      </div>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="space-y-1.5">
        <Label>Weekday</Label>
        <Select
          options={[{ value: '', label: 'Weekday' }, ...WEEKDAY_OPTIONS]}
          value={props.value.weekday}
          onChange={weekday => set({ weekday })}
          ariaLabel="Weekday"
        />
      </div>
      <ScheduleNumberField
        label="Hour"
        value={props.value.hour}
        min={0}
        max={23}
        placeholder="9"
        onChange={hour => set({ hour })}
      />
      <ScheduleNumberField
        label="Minute"
        value={props.value.minute}
        min={0}
        max={59}
        placeholder="0"
        onChange={minute => set({ minute })}
      />
    </div>
  )
}

function ScheduleNumberField(props: {
  label: string
  value: string
  min: number
  max: number
  placeholder: string
  onChange: (value: string) => void
}) {
  const reactId = useId()
  const inputId = `${reactId}-schedule-${props.label.toLowerCase()}`

  return (
    <div className="space-y-1.5">
      <Label htmlFor={inputId}>{props.label}</Label>
      <Input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={props.min}
        max={props.max}
        step={1}
        value={props.value}
        placeholder={props.placeholder}
        onChange={event => {
          const raw = event.target.value
          if (raw === '' || /^\d{1,2}$/.test(raw)) props.onChange(raw)
        }}
      />
    </div>
  )
}
