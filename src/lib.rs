use {
    itertools::Itertools as _,
    serde::Deserialize,
    serde_with::{
        base64::Base64,
        serde_as,
    },
    tiny_skia::{
        IntRect,
        Pixmap,
        PixmapPaint,
        Transform,
    },
    url::Url,
    uuid::Uuid,
    wheel::traits::ReqwestResponseExt as _,
};

#[derive(Deserialize)]
struct MinecraftProfile {
    properties: Vec<Property>,
}

#[serde_as]
#[derive(Deserialize)]
#[serde(tag = "name", rename_all = "lowercase")]
enum Property {
    Textures {
        #[serde_as(as = "Base64")]
        value: String,
    },
}

#[derive(Deserialize)]
struct Textures {
    textures: TexturesTextures,
}

#[derive(Deserialize)]
#[serde(rename_all = "UPPERCASE")]
struct TexturesTextures {
    skin: Skin,
}

#[derive(Deserialize)]
struct Skin {
    url: Url,
    #[serde(default)]
    metadata: SkinMetadata,
}

#[derive(Default, Deserialize)]
struct SkinMetadata {
    model: Model,
}

#[derive(Default, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Model {
    #[default]
    #[serde(skip)]
    Default,
    Slim,
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error(transparent)] Http(#[from] reqwest::Error),
    #[error(transparent)] Json(#[from] serde_json::Error),
    #[error(transparent)] Png(#[from] png::DecodingError),
    #[error(transparent)] Wheel(#[from] wheel::Error),
    #[error("expected exactly 1 item but found 0")]
    Empty,
    #[error("missing Content-Type header")]
    MissingContentType,
    #[error("expected exactly 1 item but found 2 or more")]
    Multiple,
    #[error("expected image/png content type but got {}", .0.to_str().unwrap_or("(non-ASCII header value)"))]
    UnexpectedContentType(reqwest::header::HeaderValue),
    #[error("skin texture does not intersect expected head coordinates")]
    UnexpectedDimensions,
}

impl<I: Iterator> From<itertools::ExactlyOneError<I>> for Error {
    fn from(mut i: itertools::ExactlyOneError<I>) -> Self {
        if i.next().is_some() {
            Self::Multiple
        } else {
            Self::Empty
        }
    }
}

/// Returns the unaltered skin texture from Mojang's API.
pub async fn raw_skin(http_client: &reqwest::Client, uuid: Uuid) -> Result<(Pixmap, Model), Error> {
    let value = http_client.get(format!("https://sessionserver.mojang.com/session/minecraft/profile/{}", uuid.simple()))
        .send().await?
        .detailed_error_for_status().await?
        .json_with_text_in_error::<MinecraftProfile>().await?
        .properties
        .into_iter()
        .map(|property| match property {
            Property::Textures { value } => value,
        })
        .exactly_one()?;
    let skin = serde_json::from_str::<Textures>(&value)?.textures.skin;
    let response = http_client.get(skin.url)
        .send().await?
        .detailed_error_for_status().await?;
    let content_type = response.headers().get(reqwest::header::CONTENT_TYPE).ok_or(Error::MissingContentType)?;
    if content_type != "image/png" { return Err(Error::UnexpectedContentType(content_type.clone())) }
    Ok((Pixmap::decode_png(&response.bytes().await?)?, skin.metadata.model))
}

/// Returns an 8×8 image showing the player's head (with hat layer).
pub async fn head(http_client: &reqwest::Client, uuid: Uuid) -> Result<Pixmap, Error> {
    let (texture, _) = raw_skin(http_client, uuid).await?;
    let mut head = texture.clone_rect(IntRect::from_ltrb(8, 8, 16, 16).unwrap()).ok_or(Error::UnexpectedDimensions)?;
    head.draw_pixmap(0, 0, texture.clone_rect(IntRect::from_ltrb(40, 8, 48, 16).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None);
    Ok(head)
}

/// Returns a 16×32 image showing a front view of the player's skin (with hat layer).
pub async fn front(http_client: &reqwest::Client, uuid: Uuid) -> Result<Pixmap, Error> {
    let (texture, model) = raw_skin(http_client, uuid).await?;
    let mut front = Pixmap::new(16, 32).unwrap();
    front.draw_pixmap(4, 0, texture.clone_rect(IntRect::from_ltrb(8, 8, 16, 16).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // head
    front.draw_pixmap(4, 8, texture.clone_rect(IntRect::from_ltrb(20, 20, 28, 32).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // body
    front.draw_pixmap(4, 20, texture.clone_rect(IntRect::from_ltrb(4, 20, 8, 32).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // right leg
    front.draw_pixmap(match model { Model::Slim => 1, Model::Default => 0 }, 8, texture.clone_rect(IntRect::from_ltrb(44, 20, match model { Model::Slim => 47, Model::Default => 48 }, 32).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // right arm
    match texture.height() {
        32 => { // old-style skin
            front.draw_pixmap(8, 20, texture.clone_rect(IntRect::from_ltrb(4, 20, 8, 32).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::from_scale(-1.0, 1.0).post_translate(4.0, 0.0), None); // left leg
            front.draw_pixmap(12, 8, texture.clone_rect(IntRect::from_ltrb(44, 20, match model { Model::Slim => 47, Model::Default => 48 }, 32).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::from_scale(-1.0, 1.0).post_translate(match model { Model::Slim => 3.0, Model::Default => 4.0 }, 0.0), None); // left arm
        }
        64 => { // new-style skin
            front.draw_pixmap(8, 20, texture.clone_rect(IntRect::from_ltrb(20, 52, 24, 64).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // left leg
            front.draw_pixmap(12, 8, texture.clone_rect(IntRect::from_ltrb(36, 52, match model { Model::Slim => 39, Model::Default => 40 }, 64).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // left arm
        }
        _ => return Err(Error::UnexpectedDimensions),
    }
    front.draw_pixmap(4, 0, texture.clone_rect(IntRect::from_ltrb(40, 8, 48, 16).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // hat
    if texture.height() == 64 { // new-style skin
        front.draw_pixmap(4, 8, texture.clone_rect(IntRect::from_ltrb(20, 36, 28, 48).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // jacket
        front.draw_pixmap(4, 20, texture.clone_rect(IntRect::from_ltrb(4, 36, 8, 48).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // right pants leg
        front.draw_pixmap(match model { Model::Slim => 1, Model::Default => 0 }, 8, texture.clone_rect(IntRect::from_ltrb(44, 36, match model { Model::Slim => 47, Model::Default => 48 }, 48).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // right sleeve
        front.draw_pixmap(8, 20, texture.clone_rect(IntRect::from_ltrb(4, 52, 8, 64).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // left pants leg
        front.draw_pixmap(12, 8, texture.clone_rect(IntRect::from_ltrb(52, 52, match model { Model::Slim => 55, Model::Default => 56 }, 64).unwrap()).ok_or(Error::UnexpectedDimensions)?.as_ref(), &PixmapPaint::default(), Transform::default(), None); // left sleeve
    }
    Ok(front)
}
