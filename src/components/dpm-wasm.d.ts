// 문서 개인정보 마스킹의 한글 쪽 미리보기(rhwp)가 WASM 파일 주소를 가져오는 데 쓴다.
declare module "*.wasm?url" {
  const url: string;
  export default url;
}
