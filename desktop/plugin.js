/**
 * ClearVoice — Desktop half.
 *
 * A push-to-talk speech-clarity pane: hold the button, speak naturally, check
 * the sentence ClearVoice proposes, then let it speak. The microphone is opened
 * on press and every track is stopped on release — there is no continuous
 * listening path in this file at all.
 *
 * Loaded uncompiled by the Hermes Desktop app: plain ESM, UI written as
 * jsx()/jsxs() calls, imports limited to @hermes/plugin-sdk, react and
 * react/jsx-runtime.
 *
 * The four UI pieces below are the brief's ClearVoicePane, PushToTalkButton,
 * CaptionPanel and PrivacyBadge. They live in one module because the disk
 * plugin loader resolves exactly one file per plugin; each is a separate
 * component with its own props, the way the .tsx split intended.
 */

import { haptic, host } from '@hermes/plugin-sdk'
import * as sdk from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'clearvoice'
const PANE_ROUTE = '/clearvoice'

// The plugin's own REST namespace, injected during register().
let REST = null

// Plugin-scoped persistence (ctx.storage) — the pane's own choices, not config.
let STORAGE = null
let OS = null
let FILES = null

function readPref(key, fallback) {
  try {
    const value = STORAGE && STORAGE.get(key)
    return value === undefined || value === null || value === '' ? fallback : value
  } catch (err) {
    return fallback
  }
}

function writePref(key, value) {
  try {
    if (STORAGE) STORAGE.set(key, value)
  } catch (err) {
    /* older host: the choice simply does not persist */
  }
}

// Theme-aware tokens with sensible fallbacks (the app paints the background).
const C = {
  text: 'var(--ui-text-primary, var(--foreground, inherit))',
  dim: 'var(--ui-text-secondary, var(--muted-foreground, #666))',
  faint: 'var(--ui-text-tertiary, #888)',
  accent: 'var(--ui-accent, #3b82f6)',
  border: 'var(--ui-stroke-secondary, rgba(128,128,128,0.35))',
  panel: 'var(--ui-surface-secondary, rgba(128,128,128,0.06))',
  danger: 'var(--ui-danger, #d92d20)',
  ok: 'var(--ui-success, #067647)'
}

const STATES = {
  ready: 'Ready',
  listening: 'Listening',
  understanding: 'Understanding',
  toSpeak: 'Ready to speak',
  speaking: 'Speaking',
  error: 'Error'
}

function statusLine(phase) {
  switch (phase) {
    case 'listening':
      return 'Listening\u2026 release when you are done.'
    case 'understanding':
      return 'Writing down what you said\u2026'
    case 'toSpeak':
      return 'Here is what I understood. Check it, then speak it.'
    case 'speaking':
      return 'Speaking\u2026'
    case 'error':
      return 'Something needs your attention.'
    default:
      return 'Hold the button and speak normally.'
  }
}

function micErrorText(err) {
  const name = err && err.name ? String(err.name) : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'The microphone is blocked. Allow microphone access for Hermes in your system settings, then try again.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No microphone was found. Connect one, then try again.'
  }
  if (name === 'NotReadableError' || name === 'AbortError') {
    return 'The microphone is in use by another app. Close it and try again.'
  }
  return 'The microphone could not start. Check your system sound settings, then try again.'
}

function restErrorText(err) {
  if (!err) return 'Something went wrong. Try again.'
  const detail = (err.detail && (err.detail.detail || err.detail.message)) || err.detail
  const status = err.status || err.statusCode
  if (typeof detail === 'string' && detail) return detail
  if (status === 403) return 'Cloud speech is off. Turn it on in Settings, or switch to the on-device voice.'
  if (status === 422) return "I didn't catch that - try again."
  return 'The speech pipeline did not answer. Check that the agent half is enabled, then try again.'
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Could not read the recording.'))
    reader.onload = () => {
      const result = String(reader.result || '')
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.readAsDataURL(blob)
  })
}

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return ''
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

// ---------------------------------------------------------------------------
// PushToTalkButton — the whole product in one control.
// ---------------------------------------------------------------------------

function PushToTalkButton({ phase, onStart, onStop, disabled }) {
  const listening = phase === 'listening'
  const busy = phase === 'understanding' || phase === 'speaking'

  const start = useCallback(() => {
    if (disabled || listening || busy) return
    haptic('tap')
    void onStart()
  }, [busy, disabled, listening, onStart])

  const stop = useCallback(() => {
    if (!listening) return
    haptic('tap')
    onStop()
  }, [listening, onStop])

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '10px' },
    children: [
      jsx('button', {
        type: 'button',
        'aria-pressed': listening,
        'aria-label': listening ? 'Listening. Release to finish.' : 'Push to talk. Hold while you speak.',
        disabled: disabled || busy,
        onPointerDown: event => {
          event.preventDefault()
          event.currentTarget.setPointerCapture?.(event.pointerId)
          start()
        },
        onPointerUp: stop,
        onPointerCancel: stop,
        onPointerLeave: event => {
          if (event.buttons === 0) stop()
        },
        onKeyDown: event => {
          if (event.key !== ' ' && event.key !== 'Enter') return
          event.preventDefault()
          if (!event.repeat) start()
        },
        onKeyUp: event => {
          if (event.key !== ' ' && event.key !== 'Enter') return
          event.preventDefault()
          stop()
        },
        style: {
          width: '100%',
          minHeight: '148px',
          padding: '18px 16px',
          borderRadius: '18px',
          border: `3px solid ${listening ? C.accent : C.border}`,
          background: listening ? C.accent : C.panel,
          color: listening ? '#fff' : C.text,
          fontSize: '1.5rem',
          fontWeight: 700,
          letterSpacing: '0.01em',
          lineHeight: 1.2,
          cursor: disabled || busy ? 'progress' : listening ? 'grabbing' : 'pointer',
          touchAction: 'none',
          userSelect: 'none',
          transition: 'background 120ms ease, border-color 120ms ease',
          outline: 'none'
        },
        children: listening ? 'Listening \u2026 release' : 'Push to talk'
      }),
      jsx('div', {
        'aria-hidden': true,
        style: { textAlign: 'center', fontSize: '0.9375rem', color: C.faint, minHeight: '1.25rem' },
        children: listening ? 'Speak naturally. Take your time.' : 'Hold, or hold Space while focused.'
      })
    ]
  })
}

// ---------------------------------------------------------------------------
// CaptionPanel — the sentence, big; the raw transcript, small.
// ---------------------------------------------------------------------------

function CaptionPanel({ phase, draft, transcript, proposal, onDraft, editing, setEditing }) {
  if (!draft && !transcript) {
    return jsx('div', {
      style: {
        minHeight: '96px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        borderRadius: '14px',
        border: `1px dashed ${C.border}`,
        color: C.faint,
        fontSize: '1.0625rem',
        textAlign: 'center'
      },
      children: 'Your words will appear here, big and clear, before anything is spoken.'
    })
  }

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '10px' },
    children: [
      editing
        ? jsx('textarea', {
            'aria-label': 'Edit the sentence before speaking it',
            value: draft,
            autoFocus: true,
            rows: 3,
            onChange: event => onDraft(event.target.value),
            style: {
              width: '100%',
              padding: '14px',
              borderRadius: '14px',
              border: `2px solid ${C.accent}`,
              background: 'transparent',
              color: C.text,
              fontSize: '1.375rem',
              lineHeight: 1.4,
              resize: 'vertical',
              fontFamily: 'inherit'
            }
          })
        : jsx('div', {
            role: 'status',
            'aria-live': 'polite',
            style: {
              padding: '16px',
              borderRadius: '14px',
              border: `2px solid ${proposal && proposal.needs_confirmation ? C.accent : C.border}`,
              fontSize: '1.5rem',
              lineHeight: 1.35,
              fontWeight: 600,
              color: C.text,
              wordBreak: 'break-word'
            },
            children: draft || statusLine(phase)
          }),
      transcript && transcript !== draft
        ? jsx('div', {
            style: { fontSize: '1rem', color: C.faint, lineHeight: 1.4 },
            children: `You said: \u201c${transcript}\u201d`
          })
        : null,

    ]
  })
}

// ---------------------------------------------------------------------------
// PrivacyBadge — always visible, never a toggle.
// ---------------------------------------------------------------------------

function PrivacyBadge({ status, onClear, clearing }) {
  const cloud = status && status.allow_cloud
  const sttLabel = (status && status.stt_label) || 'On-device'
  const ttsLabel = (status && status.tts_label) || 'On-device (Phonon 31m)'

  return jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      padding: '10px 12px',
      borderRadius: '12px',
      border: `1px solid ${C.border}`,
      background: C.panel,
      fontSize: '0.875rem',
      color: C.dim
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' },
        children: [
          jsxs('div', {
            style: { display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, color: C.ok },
            children: [
              jsx('span', {
                'aria-hidden': true,
                style: { width: '9px', height: '9px', borderRadius: '50%', background: C.ok, display: 'inline-block' }
              }),
              jsx('span', { children: 'Audio processed this session only. Nothing saved.' })
            ]
          }),
          jsx('button', {
            type: 'button',
            onClick: onClear,
            disabled: clearing,
            style: {
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.text,
              borderRadius: '8px',
              padding: '4px 10px',
              fontSize: '0.8125rem',
              cursor: 'pointer'
            },
            children: clearing ? 'Clearing\u2026' : 'Clear session'
          })
        ]
      }),
      jsxs('div', {
        style: { display: 'flex', flexWrap: 'wrap', gap: '4px 12px' },
        children: [
          jsx('span', { children: `Hearing: ${sttLabel}` }),
          jsx('span', { children: `Voice: ${ttsLabel}` }),
          jsx('span', { children: `Network: ${cloud ? 'Cloud optional' : 'Offline'}` })
        ]
      })
    ]
  })
}

// ---------------------------------------------------------------------------
// LanguageRow — language, voice and rewrite style, persisted in ctx.storage.
// ---------------------------------------------------------------------------

const LANG_LABELS = {
  en: 'English', fr: 'Français', de: 'Deutsch', es: 'Español', pt: 'Português',
  it: 'Italiano', nl: 'Nederlands', pl: 'Polski', ru: 'Русский', tr: 'Türkçe',
  ar: 'العربية', hi: 'हिन्दी', ja: '日本語', zh: '中文', ko: '한국어', th: 'ไทย', vi: 'Tiếng Việt'
}

const REWRITE_LABELS = {
  courteous: 'Courteous',
  literal: 'Literal',
  verbatim: 'Verbatim'
}

// A native <select> painted with a transparent background renders its option
// popup with no surface of its own on Linux — the labels become unreadable
// until a row is hovered. Use the app's own Select when the SDK exposes it, and
// fall back to a native control painted with the OS *system* colours
// (Canvas/CanvasText), which are opaque in both themes.
const HAS_SDK_SELECT = Boolean(sdk.Select && sdk.SelectTrigger && sdk.SelectContent && sdk.SelectItem)

function nativeSelectStyle(extra) {
  return {
    minHeight: '44px',
    width: '100%',
    borderRadius: '10px',
    border: `1px solid ${C.border}`,
    background: 'Canvas',
    color: 'CanvasText',
    colorScheme: 'light dark',
    fontSize: '1rem',
    padding: '6px 8px',
    fontFamily: 'inherit',
    cursor: 'pointer',
    ...extra
  }
}

function Picker({ label, value, options, onChange, disabled, style }) {
  const items = options || []
  if (HAS_SDK_SELECT) {
    return jsxs(sdk.Select, {
      value: value || '',
      onValueChange: onChange,
      disabled: Boolean(disabled),
      children: [
        jsx(sdk.SelectTrigger, {
          'aria-label': label,
          className: 'w-full',
          style,
          children: jsx(sdk.SelectValue, { placeholder: label })
        }),
        jsx(sdk.SelectContent, {
          children: items.map(item =>
            jsx(sdk.SelectItem, { value: item.value, children: item.label }, item.value)
          )
        })
      ]
    })
  }
  return jsx('select', {
    'aria-label': label,
    value: value || '',
    disabled,
    onChange: event => onChange(event.target.value),
    style: nativeSelectStyle(style),
    children: items.length
      ? items.map(item => jsx('option', { value: item.value, children: item.label }, item.value))
      : [jsx('option', { value: '', children: 'Default' })]
  })
}

function LanguageRow({
  language,
  voice,
  voices,
  rewriteStyle,
  languages,
  onLanguage,
  onVoice,
  onRewrite,
  busy
}) {
  const current = (languages || []).find(entry => entry.code === language)
  const needsExtra = current && current.ready === false && current.extra
  const languageOptions = Object.entries(LANG_LABELS).map(([code, label]) => ({ value: code, label }))
  const voiceOptions = (voices || []).map(entry => {
    const value = entry.voice || entry.key
    const base = entry.label || entry.name || value
    const suffix = entry.engine === 'phonon' ? '' : entry.quality ? ` · ${entry.quality}` : ''
    return { value, label: `${base}${suffix}` }
  })
  const rewriteOptions = Object.entries(REWRITE_LABELS).map(([code, label]) => ({ value: code, label }))

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '6px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', gap: '8px' },
        children: [
          jsxs('label', {
            style: { flex: '1 1 45%', display: 'flex', flexDirection: 'column', gap: '3px' },
            children: [
              jsx('span', { style: { fontSize: '0.8125rem', color: C.faint }, children: 'Language' }),
              jsx(Picker, {
                label: 'Language',
                value: language,
                options: languageOptions,
                onChange: onLanguage,
                disabled: busy
              })
            ]
          }),
          jsxs('label', {
            style: { flex: '1 1 45%', display: 'flex', flexDirection: 'column', gap: '3px' },
            children: [
              jsx('span', { style: { fontSize: '0.8125rem', color: C.faint }, children: 'Voice' }),
              jsx(Picker, {
                label: 'Voice',
                value: voice,
                options: voiceOptions,
                onChange: onVoice,
                disabled: busy || !voiceOptions.length
              })
            ]
          })
        ]
      }),
      jsxs('label', {
        style: { display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8125rem', color: C.faint },
        children: [
          jsx('span', { children: 'Rewrite' }),
          jsx(Picker, {
            label: 'Rewrite style',
            value: rewriteStyle,
            options: rewriteOptions,
            onChange: onRewrite,
            disabled: busy,
            style: { width: 'auto', minWidth: '9rem', minHeight: '36px', fontSize: '0.875rem' }
          })
        ]
      }),
      needsExtra
        ? jsx('div', {
            style: { fontSize: '0.8125rem', color: C.danger, lineHeight: 1.35 },
            children: `This language's voice needs an extra package: ${current.extra}. Recognition still works; speaking it does not until that is installed.`
          })
        : null
    ]
  })
}

// ---------------------------------------------------------------------------
// MyPhrases — explicit save only.
// ---------------------------------------------------------------------------

function MyPhrases({ phrases, folder, customFolder, onUse, onDelete, onSave, onChooseFolder, onReveal, canSave, saving, choosing }) {
  return jsxs('section', {
    'aria-label': 'My phrases',
    style: { display: 'flex', flexDirection: 'column', gap: '8px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' },
        children: [
          jsx('h3', { style: { margin: 0, fontSize: '1rem', fontWeight: 700, color: C.text }, children: 'My phrases' }),
          jsx('button', {
            type: 'button',
            onClick: onSave,
            disabled: !canSave || saving,
            style: {
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: canSave ? C.text : C.faint,
              borderRadius: '8px',
              padding: '5px 10px',
              fontSize: '0.8125rem',
              cursor: canSave ? 'pointer' : 'not-allowed'
            },
            children: saving ? 'Saving\u2026' : 'Save phrase'
          })
        ]
      }),
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', fontSize: '0.75rem', color: C.faint },
        children: [
          jsx('span', {
            title: folder || '',
            style: { flex: '1 1 100%', wordBreak: 'break-all', lineHeight: 1.35 },
            children: `Folder: ${folder || 'plugin data directory'}${customFolder ? '' : ' (default)'}`
          }),
          jsx('button', {
            type: 'button',
            onClick: onChooseFolder,
            disabled: choosing,
            style: {
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.text,
              borderRadius: '8px',
              padding: '4px 9px',
              fontSize: '0.75rem',
              cursor: 'pointer'
            },
            children: choosing ? 'Choosing\u2026' : 'Choose folder\u2026'
          }),
          jsx('button', {
            type: 'button',
            onClick: onReveal,
            style: {
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.dim,
              borderRadius: '8px',
              padding: '4px 9px',
              fontSize: '0.75rem',
              cursor: 'pointer'
            },
            children: 'Open folder'
          })
        ]
      }),
      phrases.length === 0
        ? jsx('p', {
            style: { margin: 0, fontSize: '0.9375rem', color: C.faint },
            children: 'Nothing saved. Save phrase stores only the sentence you choose \u2014 never your recordings.'
          })
        : jsx('ul', {
            style: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '6px' },
            children: phrases.map(phrase =>
              jsxs(
                'li',
                {
                  style: { display: 'flex', alignItems: 'center', gap: '8px' },
                  children: [
                    jsx('button', {
                      type: 'button',
                      onClick: () => onUse(phrase),
                      style: {
                        flex: 1,
                        textAlign: 'left',
                        border: `1px solid ${C.border}`,
                        background: 'transparent',
                        color: C.text,
                        borderRadius: '10px',
                        padding: '9px 11px',
                        fontSize: '1rem',
                        cursor: 'pointer'
                      },
                      children: phrase.text
                    }),
                    jsx('button', {
                      type: 'button',
                      'aria-label': `Delete \u201c${phrase.text}\u201d`,
                      onClick: () => onDelete(phrase),
                      style: {
                        border: `1px solid ${C.border}`,
                        background: 'transparent',
                        color: C.faint,
                        borderRadius: '8px',
                        padding: '9px 10px',
                        fontSize: '0.9375rem',
                        cursor: 'pointer'
                      },
                      children: '\u00d7'
                    })
                  ]
                },
                phrase.id
              )
            )
          })
    ]
  })
}

// ---------------------------------------------------------------------------
// Dictionary — the personal word list that measurably improves accuracy.
// ---------------------------------------------------------------------------

function Dictionary({ dictionary, learning, newTerm, onNewTerm, onAdd, onRemoveTerm, onClearCorrections, onToggleLearning }) {
  const terms = (dictionary && dictionary.terms) || []
  const corrections = (dictionary && dictionary.corrections) || []

  return jsxs('section', {
    'aria-label': 'Personal dictionary',
    style: { display: 'flex', flexDirection: 'column', gap: '8px' },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px' },
        children: [
          jsx('h3', { style: { margin: 0, fontSize: '1rem', fontWeight: 700, color: C.text }, children: 'Personal dictionary' }),
          jsx('span', { style: { fontSize: '0.75rem', color: C.faint }, children: `${terms.length} words · ${corrections.length} learned` })
        ]
      }),
      jsx('p', {
        style: { margin: 0, fontSize: '0.8125rem', color: C.faint, lineHeight: 1.4 },
        children:
          'Names, places and words you use often. Adding them makes the recogniser prefer them, which matters more than a bigger model.'
      }),
      jsxs('label', {
        style: { display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '0.8125rem', color: C.dim, lineHeight: 1.35 },
        children: [
          jsx('input', {
            type: 'checkbox',
            checked: Boolean(learning),
            onChange: event => onToggleLearning(event.target.checked),
            style: { marginTop: '2px', width: '18px', height: '18px' }
          }),
          jsx('span', {
            children:
              'Learn from my corrections — off by default. When on, fixing a sentence teaches these rules. Stored only on this machine; nothing is shared.'
          })
        ]
      }),
      jsxs('div', {
        style: { display: 'flex', gap: '6px' },
        children: [
          jsx('input', {
            type: 'text',
            value: newTerm,
            placeholder: 'Add a word or short phrase',
            'aria-label': 'Add a word to the dictionary',
            onChange: event => onNewTerm(event.target.value),
            onKeyDown: event => {
              if (event.key === 'Enter') {
                event.preventDefault()
                onAdd()
              }
            },
            style: {
              flex: 1,
              minHeight: '38px',
              borderRadius: '9px',
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.text,
              fontSize: '0.9375rem',
              padding: '4px 9px',
              fontFamily: 'inherit'
            }
          }),
          jsx('button', {
            type: 'button',
            onClick: onAdd,
            disabled: !String(newTerm || '').trim(),
            style: {
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: String(newTerm || '').trim() ? C.text : C.faint,
              borderRadius: '9px',
              padding: '4px 12px',
              fontSize: '0.8125rem',
              cursor: 'pointer'
            },
            children: 'Add'
          })
        ]
      }),
      terms.length
        ? jsx('div', {
            style: { display: 'flex', flexWrap: 'wrap', gap: '5px' },
            children: terms.map(term =>
              jsxs(
                'span',
                {
                  style: {
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    border: `1px solid ${C.border}`,
                    borderRadius: '999px',
                    padding: '2px 8px',
                    fontSize: '0.8125rem',
                    color: C.text
                  },
                  children: [
                    jsx('span', { children: term }),
                    jsx('button', {
                      type: 'button',
                      'aria-label': `Remove ${term}`,
                      onClick: () => onRemoveTerm(term),
                      style: { border: 'none', background: 'transparent', color: C.faint, cursor: 'pointer', padding: 0, fontSize: '0.875rem' },
                      children: '\u00d7'
                    })
                  ]
                },
                term
              )
            )
          })
        : null,
      corrections.length
        ? jsxs('div', {
            style: { display: 'flex', flexDirection: 'column', gap: '4px' },
            children: [
              jsx('div', {
                style: { fontSize: '0.75rem', color: C.faint },
                children: 'Learned corrections (what it heard → what you meant)'
              }),
              jsx('div', {
                style: { display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '120px', overflowY: 'auto' },
                children: corrections
                  .slice(-8)
                  .reverse()
                  .map((entry, index) =>
                    jsx(
                      'div',
                      {
                        style: { fontSize: '0.8125rem', color: C.dim },
                        children: `“${entry.heard}” → “${entry.said}”${entry.count > 1 ? ` ×${entry.count}` : ''}`
                      },
                      `${entry.heard}-${entry.said}-${index}`
                    )
                  )
              }),
              jsx('button', {
                type: 'button',
                onClick: onClearCorrections,
                style: {
                  alignSelf: 'flex-start',
                  border: `1px solid ${C.border}`,
                  background: 'transparent',
                  color: C.faint,
                  borderRadius: '8px',
                  padding: '3px 9px',
                  fontSize: '0.75rem',
                  cursor: 'pointer'
                },
                children: 'Forget learned corrections'
              })
            ]
          })
        : null
    ]
  })
}

// ---------------------------------------------------------------------------
// ClearVoice — the pane and the page.
// ---------------------------------------------------------------------------

function ClearVoice({ compact }) {
  const [phase, setPhase] = useState('ready')
  const [status, setStatus] = useState(null)
  const [transcript, setTranscript] = useState('')
  const [draft, setDraft] = useState('')
  const [proposal, setProposal] = useState(null)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const [phrases, setPhrases] = useState([])
  const [saving, setSaving] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [language, setLanguage] = useState('en')
  const [voice, setVoice] = useState('')
  const [voices, setVoices] = useState([])
  const [rewriteStyle, setRewriteStyle] = useState('verbatim')
  // A sentence a tool queued: shown, never played, until the user presses Speak it.
  const [pendingSpeech, setPendingSpeech] = useState(null)
  const pendingIdRef = useRef(null)

  // Editing takes the sentence over: the queued text (and its token) no longer
  // describes what is on screen, so the token must not be redeemed.
  const editDraft = useCallback(value => {
    setDraft(value)
    setPendingSpeech(null)
  }, [])
  const [phrasesFolder, setPhrasesFolder] = useState('')
  const [phrasesFolderCustom, setPhrasesFolderCustom] = useState(false)
  const [choosingFolder, setChoosingFolder] = useState(false)
  const [dictionary, setDictionary] = useState({ terms: [], corrections: [], hotwords: '' })
  const [learning, setLearning] = useState(false)
  const [newTerm, setNewTerm] = useState('')

  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const releasePending = useRef(false)
  const playerRef = useRef(null)
  const mounted = useRef(true)

  const refreshStatus = useCallback(async () => {
    if (!REST) return
    try {
      setStatus(await REST('/status', { method: 'GET' }))
    } catch (err) {
      /* the backend half may be off; the pane still works for capture */
    }
  }, [])

  const refreshPhrases = useCallback(async () => {
    if (!REST) return
    try {
      const dir = readPref('phrasesDir', '')
      const query = dir ? `?phrases_dir=${encodeURIComponent(dir)}` : ''
      const data = await REST(`/phrases${query}`, { method: 'GET' })
      if (!mounted.current) return
      setPhrases((data && data.phrases) || [])
      if (data && data.folder) {
        setPhrasesFolder(data.folder)
        setPhrasesFolderCustom(Boolean(dir))
      }
    } catch (err) {
      /* ignore */
    }
  }, [])

  const refreshVoices = useCallback(
    async code => {
      if (!REST) return
      try {
        const data = await REST(`/voices?language=${encodeURIComponent(code)}`, { method: 'GET' })
        if (!mounted.current) return
        const list = (data && data.voices) || []
        setVoices(list)
        setVoice(current => {
          const values = list.map(entry => entry.voice || entry.key)
          if (current && values.includes(current)) return current
          return values[0] || ''
        })
      } catch (err) {
        /* the backend half may be off; the picker stays empty */
      }
    },
    []
  )

  const refreshDictionary = useCallback(async () => {
    if (!REST) return
    try {
      const dir = readPref('phrasesDir', '')
      const query = dir ? `?phrases_dir=${encodeURIComponent(dir)}` : ''
      const data = await REST(`/dictionary${query}`, { method: 'GET' })
      if (!mounted.current) return
      setDictionary({
        terms: (data && data.terms) || [],
        corrections: (data && data.corrections) || [],
        hotwords: (data && data.hotwords) || ''
      })
    } catch (err) {
      /* ignore */
    }
  }, [])

  const learnFromEdit = useCallback(async () => {
    if (!learning || !REST) return
    const heard = (transcript || '').trim()
    const said = (draft || '').trim()
    if (!heard || !said || heard.toLowerCase() === said.toLowerCase()) return
    try {
      const dir = readPref('phrasesDir', '')
      await REST('/dictionary/learn', {
        method: 'POST',
        body: { heard, said, learning: true, phrases_dir: dir }
      })
      await refreshDictionary()
    } catch (err) {
      /* learning is best-effort; never block the turn */
    }
  }, [learning, transcript, draft, refreshDictionary])

  const stopTracks = useCallback(() => {
    const stream = streamRef.current
    streamRef.current = null
    if (stream) {
      try {
        stream.getTracks().forEach(track => track.stop())
      } catch (err) {
        /* ignore */
      }
    }
  }, [])

  const resetTurn = useCallback(() => {
    pendingIdRef.current = null
    setTranscript('')
    setDraft('')
    setProposal(null)
    setPendingSpeech(null)
    setEditing(false)
    setError('')
    setPhase('ready')
    // Drop the queued sentence too, so its token cannot be redeemed later.
    if (REST) {
      REST('/pending', { method: 'DELETE' }).catch(() => {})
    }
  }, [])

  const playAudio = useCallback((base64, onDone) => {
    try {
      if (playerRef.current) {
        playerRef.current.pause()
        playerRef.current = null
      }
      const player = new Audio(`data:audio/wav;base64,${base64}`)
      playerRef.current = player
      player.onended = () => {
        if (mounted.current) {
          setPhase('toSpeak')
          if (onDone) onDone()
        }
      }
      player.onerror = () => {
        if (!mounted.current) return
        setError('The audio could not be played. Check the system output device, then try again.')
        setPhase('error')
      }
      void player.play().catch(() => {
        if (!mounted.current) return
        setError('Playback was blocked. Tap Speak it once more to hear it.')
        setPhase('toSpeak')
      })
    } catch (err) {
      setError('The audio could not be played.')
      setPhase('error')
    }
  }, [])

  const finishRecording = useCallback(
    async mimeType => {
      stopTracks()
      recorderRef.current = null
      const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
      chunksRef.current = []
      if (blob.size < 600) {
        setPhase('error')
        setError("I didn't catch that - try again, a little closer to the microphone.")
        return
      }
      setPhase('understanding')
      try {
        const audio_b64 = await blobToBase64(blob)
        const data = await REST('/transcribe', {
          method: 'POST',
          body: { audio_b64, mime: mimeType || 'audio/webm', language, rewrite_style: rewriteStyle }
        })
        if (!mounted.current) return
        const next = data && data.proposal ? data.proposal : null
        setTranscript((data && data.transcript) || '')
        setProposal(next)
        setDraft((next && next.message) || '')
        if (data && data.status) setStatus(data.status)
        setPhase('toSpeak')
        haptic('success')
      } catch (err) {
        if (!mounted.current) return
        setError(restErrorText(err))
        setPhase('error')
      }
    },
    [stopTracks, language, rewriteStyle]
  )

  const startRecording = useCallback(async () => {
    pendingIdRef.current = null
    setError('')
    setTranscript('')
    setDraft('')
    setProposal(null)
    setPendingSpeech(null)
    setEditing(false)
    setPhase('listening')
    if (REST) {
      REST('/pending', { method: 'DELETE' }).catch(() => {})
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      })
      if (!mounted.current) {
        stream.getTracks().forEach(track => track.stop())
        return
      }
      streamRef.current = stream
      const mimeType = pickMimeType()
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = event => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        void finishRecording(recorder.mimeType || mimeType || 'audio/webm')
      }
      recorder.start()
      recorderRef.current = recorder
      if (releasePending.current) {
        releasePending.current = false
        recorder.stop()
      }
    } catch (err) {
      releasePending.current = false
      stopTracks()
      setError(micErrorText(err))
      setPhase('error')
    }
  }, [finishRecording, stopTracks])

  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder) {
      releasePending.current = true
      return
    }
    if (recorder.state === 'inactive') return
    try {
      recorder.stop() // onstop stops the tracks and sends the clip
    } catch (err) {
      stopTracks()
      setError("That recording ended early. Try again.")
      setPhase('error')
    }
  }, [stopTracks])

  const speak = useCallback(async () => {
    const message = draft.trim()
    if (!message) {
      setError('There is nothing to speak yet.')
      setPhase('error')
      return
    }
    setPhase('speaking')
    setError('')
    try {
      const body = pendingSpeech && pendingSpeech.token
        ? { token: pendingSpeech.token, approved: true, language, voice }
        : { message, approved: true, language, voice }
      const data = await REST('/speak', { method: 'POST', body })
      setPendingSpeech(null)
      if (!mounted.current) return
      if (data && data.backend && data.backend !== 'phonon') {
        // Cloud use is never silent: say so in the badge line.
        await refreshStatus()
      }
      setTranscript(message)
      playAudio(data.audio_b64)
    } catch (err) {
      if (!mounted.current) return
      setError(restErrorText(err))
      setPhase('error')
    }
  }, [draft, pendingSpeech, playAudio, refreshStatus, language, voice])

  const addTerm = useCallback(async () => {
    const term = newTerm.trim()
    if (!term) return
    try {
      const dir = readPref('phrasesDir', '')
      await REST('/dictionary/terms', { method: 'POST', body: { term, phrases_dir: dir } })
      setNewTerm('')
      await refreshDictionary()
    } catch (err) {
      setError(restErrorText(err))
    }
  }, [newTerm, refreshDictionary])

  const removeTerm = useCallback(
    async term => {
      try {
        const dir = readPref('phrasesDir', '')
        const query = dir ? `&phrases_dir=${encodeURIComponent(dir)}` : ''
        await REST(`/dictionary/terms?term=${encodeURIComponent(term)}${query}`, { method: 'DELETE' })
        await refreshDictionary()
      } catch (err) {
        /* ignore */
      }
    },
    [refreshDictionary]
  )

  const clearCorrections = useCallback(async () => {
    try {
      const dir = readPref('phrasesDir', '')
      const query = dir ? `?phrases_dir=${encodeURIComponent(dir)}` : ''
      await REST(`/dictionary/corrections${query}`, { method: 'DELETE' })
      await refreshDictionary()
    } catch (err) {
      /* ignore */
    }
  }, [refreshDictionary])

  const clearSession = useCallback(async () => {
    setClearing(true)
    try {
      await REST('/session/clear', { method: 'POST', body: {} })
    } catch (err) {
      /* nothing to do — memory is cleared with the plugin anyway */
    }
    resetTurn()
    setClearing(false)
  }, [resetTurn])

  const savePhrase = useCallback(async () => {
    const text = draft.trim()
    if (!text) return
    setSaving(true)
    try {
      const dir = readPref('phrasesDir', '')
      await REST('/phrases', { method: 'POST', body: { text, explicit: true, phrases_dir: dir } })
      await refreshPhrases()
    } catch (err) {
      setError(restErrorText(err))
    }
    setSaving(false)
  }, [draft, refreshPhrases])

  const choosePhrasesFolder = useCallback(async () => {
    if (!FILES || typeof FILES.requestFolder !== 'function') {
      setError('This build of the Desktop app cannot open a folder picker. Set "Saved phrases folder" in Settings > Plugins > ClearVoice instead.')
      return
    }
    setChoosingFolder(true)
    try {
      const picked = await FILES.requestFolder()
      if (picked && picked.ok && picked.folder && picked.folder.path) {
        writePref('phrasesDir', picked.folder.path)
        await refreshPhrases()
      }
    } catch (err) {
      setError('The folder picker could not open. Set "Saved phrases folder" in Settings > Plugins > ClearVoice instead.')
    }
    setChoosingFolder(false)
  }, [refreshPhrases])

  const revealPhrasesFolder = useCallback(() => {
    if (!OS || typeof OS.revealPath !== 'function' || !phrasesFolder) return
    void OS.revealPath(phrasesFolder)
  }, [phrasesFolder])

  const deletePhrase = useCallback(
    async phrase => {
      try {
        const dir = readPref('phrasesDir', '')
        const query = dir ? `?phrases_dir=${encodeURIComponent(dir)}` : ''
        await REST(`/phrases/${phrase.id}${query}`, { method: 'DELETE' })
      } catch (err) {
        /* ignore */
      }
      await refreshPhrases()
    },
    [refreshPhrases]
  )

  // Load status + phrases on mount, poll for audio the agent asked us to speak.
  useEffect(() => {
    mounted.current = true
    const savedLanguage = readPref('language', 'en')
    const savedVoice = readPref('voice', '')
    const savedStyle = readPref('rewriteStyle', 'verbatim')
    setLanguage(savedLanguage)
    setVoice(savedVoice)
    setRewriteStyle(savedStyle)
    setLearning(readPref('learning', false) === true)
    void refreshStatus()
    void refreshPhrases()
    void refreshDictionary()
    void refreshVoices(savedLanguage)
    const timer = setInterval(async () => {
      if (!REST) return
      try {
        const data = await REST('/pending', { method: 'GET' })
        const alreadyShown = pendingIdRef.current !== null && pendingIdRef.current === (data && data.id)
        if (!data || !data.pending) {
          pendingIdRef.current = null
        }
        if (data && data.pending && mounted.current && !alreadyShown) {
          pendingIdRef.current = data.id
          // Text only. Nothing is synthesised or played here: the user has not
          // pressed anything, so this is a proposal like any other.
          const queuedText = (data.text || '').trim()
          setPendingSpeech({
            token: data.token,
            id: data.id,
            kind: data.kind || 'speak',
            text: queuedText
          })
          setTranscript(((data.transcript || '') || queuedText).trim())
          setDraft(queuedText)
          setProposal({
            message: queuedText,
            needs_confirmation: true,
            confirmation_question: 'ClearVoice is asking to speak this out loud. Nothing has been said yet.',
            candidates: [queuedText],
            reason: 'queued_by_tool'
          })
          setPhase('toSpeak')
        }
      } catch (err) {
        /* backend asleep */
      }
    }, 4000)
    return () => {
      mounted.current = false
      clearInterval(timer)
      stopTracks()
      if (playerRef.current) {
        try {
          playerRef.current.pause()
        } catch (err) {
          /* ignore */
        }
        playerRef.current = null
      }
    }
  }, [playAudio, refreshPhrases, refreshStatus, refreshVoices, refreshDictionary, stopTracks])

  const listening = phase === 'listening'
  const busy = phase === 'understanding' || phase === 'speaking'
  const showActions = Boolean(draft) && !listening && !busy

  return jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '14px',
      padding: compact ? '12px' : '20px',
      height: '100%',
      overflowY: 'auto',
      boxSizing: 'border-box',
      color: C.text,
      fontSize: '1.125rem'
    },
    children: [
      jsxs('header', {
        style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px' },
        children: [
          jsx('h2', {
            style: { margin: 0, fontSize: compact ? '1.25rem' : '1.5rem', fontWeight: 700 },
            children: 'ClearVoice'
          }),
          jsx('span', {
            style: { fontSize: '0.875rem', color: C.faint },
            children: STATES[phase] || STATES.ready
          })
        ]
      }),

      jsx(LanguageRow, {
        language,
        voice,
        voices,
        rewriteStyle,
        languages: (status && status.languages) || [],
        busy: listening || busy,
        onLanguage: code => {
          setLanguage(code)
          setVoice('')
          writePref('language', code)
          void refreshVoices(code)
        },
        onVoice: value => {
          setVoice(value)
          writePref('voice', value)
        },
        onRewrite: value => {
          setRewriteStyle(value)
          writePref('rewriteStyle', value)
        }
      }),


      jsx(PushToTalkButton, {
        phase,
        disabled: false,
        onStart: startRecording,
        onStop: stopRecording
      }),

      jsx(CaptionPanel, {
        phase,
        draft,
        transcript,
        proposal,
        editing,
        setEditing,
        onDraft: editDraft
      }),

      proposal && proposal.needs_confirmation && proposal.confirmation_question
        ? jsxs('div', {
            style: {
              padding: '12px',
              borderRadius: '12px',
              border: `1px solid ${C.accent}`,
              fontSize: '1.0625rem',
              color: C.text
            },
            children: [
              jsx('div', { style: { fontWeight: 600, marginBottom: '6px' }, children: proposal.confirmation_question }),
              proposal.reason === 'polished_only'
                ? jsx('div', {
                    style: { fontSize: '0.875rem', color: C.dim, marginBottom: '8px' },
                    children:
                      'Tidied and made polite — the words are yours, the order was not changed. Full sentence rebuilding is English and French only.'
                  })
                : null,
              jsx('div', {
                style: { display: 'flex', flexDirection: 'column', gap: '6px' },
                children: (proposal.candidates || []).map(candidate =>
                  jsx(
                    'button',
                    {
                      type: 'button',
                      onClick: () => {
                        editDraft(candidate)
                        setProposal(null)
                      },
                      style: {
                        textAlign: 'left',
                        border: `1px solid ${C.border}`,
                        background: 'transparent',
                        color: C.text,
                        borderRadius: '10px',
                        padding: '10px 12px',
                        fontSize: '1.0625rem',
                        cursor: 'pointer'
                      },
                      children: candidate
                    },
                    candidate
                  )
                )
              })
            ]
          })
        : null,

      error
        ? jsx('div', {
            role: 'alert',
            style: { color: C.danger, fontSize: '1rem', lineHeight: 1.4 },
            children: error
          })
        : null,

      showActions
        ? jsxs('div', {
            style: { display: 'flex', flexWrap: 'wrap', gap: '8px' },
            children: [
              jsx('button', {
                type: 'button',
                onClick: () => void speak(),
                style: {
                  flex: '1 1 160px',
                  minHeight: '56px',
                  borderRadius: '14px',
                  border: 'none',
                  background: C.accent,
                  color: '#fff',
                  fontSize: '1.25rem',
                  fontWeight: 700,
                  cursor: 'pointer'
                },
                children: 'Speak it'
              }),
              jsx('button', {
                type: 'button',
                onClick: () => {
                  if (editing) void learnFromEdit()
                  setEditing(value => !value)
                },
                style: {
                  flex: '1 1 120px',
                  minHeight: '56px',
                  borderRadius: '14px',
                  border: `1px solid ${C.border}`,
                  background: 'transparent',
                  color: C.text,
                  fontSize: '1.0625rem',
                  cursor: 'pointer'
                },
                children: editing ? 'Done editing' : 'Edit it'
              }),
              jsx('button', {
                type: 'button',
                onClick: resetTurn,
                style: {
                  flex: '1 1 120px',
                  minHeight: '56px',
                  borderRadius: '14px',
                  border: `1px solid ${C.border}`,
                  background: 'transparent',
                  color: C.text,
                  fontSize: '1.0625rem',
                  cursor: 'pointer'
                },
                children: 'Try again'
              }),
              jsx('button', {
                type: 'button',
                onClick: clearSession,
                style: {
                  flex: '1 1 100px',
                  minHeight: '56px',
                  borderRadius: '14px',
                  border: `1px solid ${C.border}`,
                  background: 'transparent',
                  color: C.dim,
                  fontSize: '1.0625rem',
                  cursor: 'pointer'
                },
                children: 'Cancel'
              })
            ]
          })
        : null,

      phase === 'error'
        ? jsx('button', {
            type: 'button',
            onClick: resetTurn,
            style: {
              minHeight: '52px',
              borderRadius: '14px',
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.text,
              fontSize: '1.0625rem',
              cursor: 'pointer'
            },
            children: 'Start over'
          })
        : null,

      jsx(MyPhrases, {
        phrases,
        folder: phrasesFolder,
        customFolder: phrasesFolderCustom,
        choosing: choosingFolder,
        onUse: phrase => {
          editDraft(phrase.text)
          setTranscript('')
          setProposal(null)
          setPhase('toSpeak')
        },
        onDelete: phrase => void deletePhrase(phrase),
        onSave: () => void savePhrase(),
        onChooseFolder: () => void choosePhrasesFolder(),
        onReveal: revealPhrasesFolder,
        canSave: Boolean(draft.trim()),
        saving
      }),

      jsx(Dictionary, {
        dictionary,
        learning,
        newTerm,
        onNewTerm: setNewTerm,
        onAdd: () => void addTerm(),
        onRemoveTerm: term => void removeTerm(term),
        onClearCorrections: () => void clearCorrections(),
        onToggleLearning: value => {
          setLearning(value)
          writePref('learning', value)
        }
      }),

      jsx(PrivacyBadge, { status, onClear: () => void clearSession(), clearing }),

      status && !status.local_tts_available
        ? jsx('div', {
            style: { fontSize: '0.9375rem', color: C.danger, lineHeight: 1.4 },
            children:
              'The on-device voice is not installed yet. Run "hermes plugins validate <plugin> --install-deps", then reload ClearVoice.'
          })
        : null,

      jsx('div', {
        style: { fontSize: '0.8125rem', color: C.faint, lineHeight: 1.4 },
        children:
          'ClearVoice never listens in the background, never sends messages, and never keeps your recordings. It may help you be understood more clearly; it is not a medical device or a substitute for speech therapy.'
      })
    ]
  })
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export default {
  id: ID,
  name: 'ClearVoice',
  defaultEnabled: false, // opt-in: nothing loads until the user enables it
  register(ctx) {
    REST = (path, opts) => ctx.rest(path, opts)
    STORAGE = ctx.storage || null
    OS = ctx.os || null
    FILES = ctx.files || null

    // The pane (compact) and the full page (roomy) render the same component.
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'clearvoice',
      data: { placement: 'right', width: '420px' },
      render: () => jsx(ClearVoice, { compact: true })
    })

    ctx.registerMany([
      {
        id: 'page',
        area: 'routes',
        data: { path: PANE_ROUTE },
        render: () => jsx(ClearVoice, { compact: false })
      },
      {
        id: 'nav',
        area: 'sidebar.nav',
        data: { path: PANE_ROUTE, label: 'ClearVoice', codicon: 'unmute' }
      },
      {
        id: 'palette',
        area: 'palette',
        data: {
          id: 'clearvoice.open',
          label: 'Open ClearVoice (push to talk)',
          keywords: ['clearvoice', 'speech', 'talk', 'voice'],
          run: () => host.navigate(PANE_ROUTE)
        }
      },
      {
        id: 'chip',
        area: 'statusBar.right',
        order: 118,
        render: () =>
          jsx('button', {
            type: 'button',
            'aria-label': 'Open ClearVoice',
            onClick: () => host.navigate(PANE_ROUTE),
            style: {
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              height: '100%',
              padding: '0 6px',
              border: 'none',
              background: 'transparent',
              color: C.faint,
              fontSize: '0.6875rem',
              cursor: 'pointer'
            },
            children: [
              jsx('span', {
                'aria-hidden': true,
                style: { width: '7px', height: '7px', borderRadius: '50%', background: C.ok, display: 'inline-block' }
              }),
              jsx('span', { children: 'clearvoice' })
            ]
          })
      }
    ])

    // /clearvoice and clearvoice_speak reach the pane through these events.
    ctx.onEvent('plugin.clearvoice.open', () => host.navigate(PANE_ROUTE))
    ctx.onEvent('plugin.clearvoice.speak', () => host.navigate(PANE_ROUTE))
  }
}
