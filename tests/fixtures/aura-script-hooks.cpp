/*
 * This file is part of the TrinityCore Project. See AUTHORS file for Copyright information
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the
 * Free Software Foundation; either version 2 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program. If not, see <http://www.gnu.org/licenses/>.
 */
// Native AuraScript methods at 91d49b230f89c3ab4719f5b2b2d1e70ed36613c4; standalone runtime-hook harness.
#include <cassert>
#include <stack>
#include <stdexcept>
#define ABORT_MSG(message) throw std::runtime_error(message)
#define TC_LOG_ERROR(...) (++warnings)
struct AuraApplication {};
enum AuraScriptHookType {
 AURA_SCRIPT_HOOK_EFFECT_APPLY, AURA_SCRIPT_HOOK_EFFECT_REMOVE, AURA_SCRIPT_HOOK_EFFECT_PERIODIC,
 AURA_SCRIPT_HOOK_EFFECT_ABSORB, AURA_SCRIPT_HOOK_EFFECT_SPLIT, AURA_SCRIPT_HOOK_PREPARE_PROC,
 AURA_SCRIPT_HOOK_PROC, AURA_SCRIPT_HOOK_EFFECT_PROC, AURA_SCRIPT_HOOK_EFFECT_MANASHIELD,
 AURA_SCRIPT_HOOK_EFFECT_AFTER_MANASHIELD
};
class AuraScript {
 struct ScriptStateStore {
  int _currentScriptState; const AuraApplication* _auraApplication; bool _defaultActionPrevented;
  ScriptStateStore(int state,const AuraApplication* app,bool prevented):
   _currentScriptState(state),_auraApplication(app),_defaultActionPrevented(prevented) {}
 };
 std::stack<ScriptStateStore> m_scriptStates;
 int m_currentScriptState=-1;
 const AuraApplication* m_auraApplication=nullptr;
 bool m_defaultActionPrevented=false;
public:
 int warnings=0;
 void _PrepareScriptCall(AuraScriptHookType,AuraApplication const*);
 void _FinishScriptCall();
 bool _IsDefaultActionPrevented() const;
 void PreventDefaultAction();
};

void AuraScript::_PrepareScriptCall(AuraScriptHookType hookType, AuraApplication const* aurApp)
{
    m_scriptStates.push(ScriptStateStore(m_currentScriptState, m_auraApplication, m_defaultActionPrevented));
    m_currentScriptState = hookType;
    m_defaultActionPrevented = false;
    m_auraApplication = aurApp;
}

void AuraScript::_FinishScriptCall()
{
    ScriptStateStore stateStore = m_scriptStates.top();
    m_currentScriptState = stateStore._currentScriptState;
    m_auraApplication = stateStore._auraApplication;
    m_defaultActionPrevented = stateStore._defaultActionPrevented;
    m_scriptStates.pop();
}

bool AuraScript::_IsDefaultActionPrevented() const
{
    switch (m_currentScriptState)
    {
        case AURA_SCRIPT_HOOK_EFFECT_APPLY:
        case AURA_SCRIPT_HOOK_EFFECT_REMOVE:
        case AURA_SCRIPT_HOOK_EFFECT_PERIODIC:
        case AURA_SCRIPT_HOOK_EFFECT_ABSORB:
        case AURA_SCRIPT_HOOK_EFFECT_SPLIT:
        case AURA_SCRIPT_HOOK_PREPARE_PROC:
        case AURA_SCRIPT_HOOK_PROC:
        case AURA_SCRIPT_HOOK_EFFECT_PROC:
            return m_defaultActionPrevented;
        default:
            ABORT_MSG("AuraScript::_IsDefaultActionPrevented is called in a wrong place");
            return false;
    }
}

void AuraScript::PreventDefaultAction()
{
    switch (m_currentScriptState)
    {
        case AURA_SCRIPT_HOOK_EFFECT_APPLY:
        case AURA_SCRIPT_HOOK_EFFECT_REMOVE:
        case AURA_SCRIPT_HOOK_EFFECT_PERIODIC:
        case AURA_SCRIPT_HOOK_EFFECT_ABSORB:
        case AURA_SCRIPT_HOOK_EFFECT_SPLIT:
        case AURA_SCRIPT_HOOK_PREPARE_PROC:
        case AURA_SCRIPT_HOOK_PROC:
        case AURA_SCRIPT_HOOK_EFFECT_PROC:
            m_defaultActionPrevented = true;
            break;
        default:
            TC_LOG_ERROR("scripts", "Script: `{}` Spell: `{}` AuraScript::PreventDefaultAction called in a hook in which the call won't have effect!", m_scriptName, m_scriptSpellId);
            break;
    }
}
int main() {
 AuraScript script;AuraApplication application;
 script._PrepareScriptCall(AURA_SCRIPT_HOOK_EFFECT_MANASHIELD,&application);
 assert(!script._IsDefaultActionPrevented());
 script.PreventDefaultAction();assert(script._IsDefaultActionPrevented()&&script.warnings==0);
 script._PrepareScriptCall(AURA_SCRIPT_HOOK_EFFECT_AFTER_MANASHIELD,&application);
 script._FinishScriptCall();
 assert(script._IsDefaultActionPrevented());
 script._FinishScriptCall();
 for(auto hook:{AURA_SCRIPT_HOOK_EFFECT_ABSORB,AURA_SCRIPT_HOOK_EFFECT_APPLY}) {
  script._PrepareScriptCall(hook,&application);
  assert(!script._IsDefaultActionPrevented());script.PreventDefaultAction();
  assert(script._IsDefaultActionPrevented());script._FinishScriptCall();
 }
 script._PrepareScriptCall(AURA_SCRIPT_HOOK_EFFECT_AFTER_MANASHIELD,&application);
 script.PreventDefaultAction();assert(script.warnings==1);script._FinishScriptCall();
}
