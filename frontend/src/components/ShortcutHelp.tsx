import { Modal } from 'antd'

import { HOTKEY_GROUPS, formatCombo, hotkeysFor } from '../hotkeys'
import { getCachedUser } from '../services/auth'
import { useShortcuts } from '../state/shortcuts'

/** 快捷键帮助面板：直接渲染与运行时同一份元数据，新增快捷键无需改这里 */
export default function ShortcutHelp() {
  const { helpOpen, setHelpOpen } = useShortcuts()
  const defs = hotkeysFor(getCachedUser()?.role === 'admin')
  return (
    <Modal
      open={helpOpen}
      title="快捷键"
      footer={null}
      width={620}
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
                  <kbd className="shortcut-help__key">{formatCombo(def.combo)}</kbd>
                </div>
              ))}
            </section>
          )
        })}
        <p className="shortcut-help__footnote">
          在输入框里打字时不会误触发（Esc 除外）；带 ⌘ / Ctrl 的组合键仍可使用。
        </p>
      </div>
    </Modal>
  )
}
