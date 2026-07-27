import { useEffect, useMemo } from "react";
import { Camera, ImagePlus, X } from "lucide-react";

export function VocPhotoUpload({ files, onChange, id, maxFiles = 3 }) {
  const previews = useMemo(() => files.map((file) => ({ file, url: URL.createObjectURL(file) })), [files]);
  useEffect(() => () => previews.forEach((preview) => URL.revokeObjectURL(preview.url)), [previews]);

  const addFiles = (event) => {
    const images = [...event.target.files].filter((file) => file.type.startsWith("image/"));
    onChange([...files, ...images].slice(0, maxFiles));
    event.target.value = "";
  };

  return <section className="voc-photo-upload">
    <div><span><Camera size={16} /></span><div><b>사진 첨부 <small>(선택)</small></b><p>불편 사항을 확인할 수 있는 사진을 최대 {maxFiles}장까지 첨부해 주세요.</p></div></div>
    {previews.length > 0 && <div className="voc-photo-previews">{previews.map((preview, index) => <figure key={`${preview.file.name}-${preview.file.lastModified}`}><img src={preview.url} alt={`첨부 사진 ${index + 1}`} /><button type="button" aria-label={`첨부 사진 ${index + 1} 삭제`} onClick={() => onChange(files.filter((_, fileIndex) => fileIndex !== index))}><X size={13} /></button><figcaption>{preview.file.name}</figcaption></figure>)}</div>}
    {files.length < maxFiles && <label htmlFor={id}><ImagePlus size={17} /><span>사진 선택</span><small>{files.length} / {maxFiles}</small></label>}
    <input id={id} type="file" accept="image/*" multiple capture="environment" onChange={addFiles} />
  </section>;
}
