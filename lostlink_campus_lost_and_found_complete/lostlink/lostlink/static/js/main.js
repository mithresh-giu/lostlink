/**
 * LostLink – Campus Lost and Found Management System
 * Client-side progressive enhancement: mobile menu toggle, image preview,
 * client-side form validation feedback, and claim modal toggle.
 */
document.addEventListener("DOMContentLoaded", function () {
  // Mobile Navigation Toggle
  const menuBtn = document.getElementById("mobile-menu-btn");
  const navLinks = document.getElementById("nav-links");
  if (menuBtn && navLinks) {
    menuBtn.addEventListener("click", function () {
      navLinks.classList.toggle("open");
    });
  }

  // Image Upload Live Preview
  const imageInput = document.getElementById("image-upload-input");
  const previewBox = document.getElementById("image-preview-container");
  const previewImg = document.getElementById("image-preview-element");
  if (imageInput && previewBox && previewImg) {
    imageInput.addEventListener("change", function (e) {
      const file = e.target.files && e.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = function (ev) {
          previewImg.src = ev.target.result;
          previewBox.style.display = "block";
        };
        reader.readAsDataURL(file);
      } else {
        previewBox.style.display = "none";
      }
    });
  }

  // Contact Owner / Claim Drawer Toggle on Item Details Page (Figure 7.6)
  const contactOwnerBtn = document.getElementById("contact-owner-btn");
  const claimFormSection = document.getElementById("claim-form-section");
  if (contactOwnerBtn && claimFormSection) {
    contactOwnerBtn.addEventListener("click", function () {
      const isHidden = claimFormSection.style.display === "none";
      claimFormSection.style.display = isHidden ? "block" : "none";
      if (isHidden) {
        claimFormSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  }
});
