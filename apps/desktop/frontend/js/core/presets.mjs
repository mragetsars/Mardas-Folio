export const PRESETS = Object.freeze({
  general: Object.freeze({id:"general",titleKey:"presetGeneral",descriptionKey:"presetGeneralHelp",options:Object.freeze({style:"modern",palette:"blue",mode:"light",page_size:"A4",toc:true,quality_profile:"standard",document_language:"auto"})}),
  academic: Object.freeze({id:"academic",titleKey:"presetAcademic",descriptionKey:"presetAcademicHelp",options:Object.freeze({style:"classic",palette:"blue",mode:"light",page_size:"A4",toc:true,quality_profile:"strict-publication",document_language:"auto",references_enabled:true,citations_enabled:true})}),
  technical: Object.freeze({id:"technical",titleKey:"presetTechnical",descriptionKey:"presetTechnicalHelp",options:Object.freeze({style:"modern",palette:"teal",mode:"light",page_size:"A4",toc:true,quality_profile:"strict-publication",document_language:"auto"})}),
  minimal: Object.freeze({id:"minimal",titleKey:"presetMinimal",descriptionKey:"presetMinimalHelp",options:Object.freeze({style:"minimal",palette:"neutral",mode:"light",page_size:"A4",toc:false,quality_profile:"standard",document_language:"auto"})}),
});
export function presetById(id){return PRESETS[id]??PRESETS.general}
export function mergePresetOptions(id,overrides={}){return {...presetById(id).options,...overrides}}
