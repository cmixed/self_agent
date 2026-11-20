import { Modal } from 'antd'
import { Fragment } from 'react'

import { HOTKEY_GROUPS, formatCombo, hotkeysFor, sequenceKeys } from '../hotkeys'
import type { HotkeyDef } from '../hotkeys'
import { getCachedUser } from '../services/auth'
import { useShortcuts } from '../state/shortcuts'

/** 每个键一颗 kbd，序列用「然后」、等价键用「或」——与 self-web 的帮助面板一致 */
function KeyCaps({ def }: { def: HotkeyDef }) {
  const combos = [def.combo, ...(def.aliases ?? [])]
  return (
    <span className="shortcut-help__caps">
      {combos.map((combo, comboIndex) => (
        <Fragment key={combo}>
          {comboIndex > 0 ? <span className="shortcut-help__join">或</span> : null}
          {sequenceKeys(combo).map((key, keyIndex) => (
            <Fragment key={`${combo}-${key}`}>
              {keyIndex > 0 ? <span className="shortcut-help__join">然后</span> : null}
              <kbd className="shortcut-help__key">{formatCombo(key)}</kbd>
            </Fragment>
          ))}
        </Fragment>
      ))}
    </span>
  )
}

/** 快捷键帮助面板：直接渲染与运行时同一份元数据，新增快捷键无需改这里 */
export default function ShortcutHelp() {
  const { helpOpen, setHelpOpen } = useShortcuts()
  const defs = hotkeysFor(getCachedUser()?.role === 'admin')
  return (
    <Modal
      open={helpOpen}
      title="快捷键"
      footer={null}
      width={640}
      className="shortcut-help-modal"
      rootClassName="shortcut-help-modal-root"
      onCancel={() => setHelpOpen(false)}
    >
      <div className="shortcut-help">
        {HOTKEY_GROUPS.map((group) => {
          const groupDefs = defs.filter((item) => item.group === group)
          if (groupDefs.length === 0) return null
          return (
            <section key={group} className="shortcut-help__group">
              <h4 className="shortcut-help__title">{group}</h4>
              {groupDefs.map((def) => (
                <div key={def.id} className="shortcut-help__row">
                  <div className="shortcut-help__info">
                    <span className="shortcut-help__label">{def.title}</span>
                    {def.description ? (
                      <span className="shortcut-help__desc">{def.description}</span>
                    ) : null}
                  </div>
                  <KeyCaps def={def} />
                </div>
              ))}
            </section>
          )
        })}
        <p className="shortcut-help__footnote">
          输入框内打字时不会误触发（Esc 除外）；带 Ctrl / ⌘ / Alt 的组合键留给浏览器。
        </p>
      </div>
    </Modal>
  )
}
